"""
Constructor de MIDI pedagógico para dictados musicales.

Consignas acumuladas (traducidas a código):
  - Tempo por convención: compuesto (6/8, 9/8, 12/8) = 50 bpm; binario = 60 bpm.
    Configurable vía parámetro.
  - 1 compás de silencio al principio.
  - Bloque intro x2: La(1c) - Tónica(1c) - La(1c) - Acordes i-iv-V-i (1 pulso c/u).
  - Acordes tonales: bajo en 3ª octava + triada cerrada; voz superior hace
    tónica-tónica-sensible-tónica con velocity destacada (92) sobre las interiores (65).
  - Separación: 2 compases entre los dos bloques de intro, 4 compases antes del 1er pase.
  - Pases: entero - primeros x4 - entero - últimos x4 - entero - entero.
  - Silencio entre pases: 8 compases.
  - Antes de cada pase: [ride opcional] + N cencerros + claqueta previa de 2 pulsos.
  - Ride (nota 59 en drum channel = B2 en Logic = Ride Cymbal 2) solo suena en
    cambio de sección (nunca en repeticiones consecutivas de la misma sección).
  - Cencerros (nota 56): N golpes según nº de repetición. Pausa 1.0 s después.
  - Claqueta previa (side stick 37): velocidades 51/60 (segundo más fuerte).
  - Click sutil durante el dictado (side stick): 19/9 con acento en downbeat.
  - Melodía acentuada en downbeat: vel 100 / resto 72.
  - Badum-tss rápido al final (2 snares + bombo+crash), ~280 ms.
  - Opción de 2ª voz (clave de fa) con programa instrumental independiente.
"""
from dataclasses import dataclass, field
from typing import Optional
import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage

# ========== Constantes de ticks ==========
PPQ = 480
QUARTER = PPQ
EIGHTH = PPQ // 2
SIXTEENTH = PPQ // 4
DOTTED_QUARTER = QUARTER + EIGHTH
DOTTED_EIGHTH = EIGHTH + SIXTEENTH

# ========== Percusión (canal 10 en MIDI = channel=9) ==========
CH_DRUMS = 9
PERC_SIDE_STICK = 37
PERC_SNARE = 38
PERC_BASS_DRUM = 36
PERC_CRASH = 49
PERC_COWBELL = 56
PERC_SECTION = 59   # B2 en Logic = Ride Cymbal 2 en GM

# ========== Gong (canal 3) ==========
CH_GONG = 2         # canal 3 MIDI -> Logic crea pista separada
PROG_GONG = 47      # Orchestra Hit (placeholder, reasignar Orchestral Kit en Logic)
GONG_NOTE = 55      # G2 en Logic (C3 = middle C = 60)

# ========== Convención de tempo ==========
def tempo_bpm_for_meter(num: int, den: int) -> int:
    """Compuesto=50, Binario=60. Ajustable."""
    is_compound = (den == 8 and num in (6, 9, 12)) or (den == 16 and num in (6, 9, 12))
    return 50 if is_compound else 60


@dataclass
class DictationInput:
    """Datos de entrada para un dictado."""
    # Eventos de la voz superior: lista de (offset_ticks, midi_note_or_None, duration_ticks)
    # offset relativo al inicio del dictado, note=None para silencio.
    melody: list                              # [(offset, note, dur), ...]
    num_measures: int                          # compases del dictado
    time_sig_num: int
    time_sig_den: int
    key_sig_label: str                         # "Gm", "C", "F", etc. (MIDI meta key)
    tonic_midi: int                            # tónica para tonos de referencia (ej. 67 = G4)
    chord_progression: list                    # lista de dicts: {'lower':[n1,n2,n3], 'top':n}
                                               # i-iv-V-i. La voz 'top' suena destacada.
    # Opcional: segunda voz (clave de fa)
    bass: Optional[list] = None                # [(offset, note, dur), ...]

    # Instrumentos (GM programs 0-127)
    melody_program: int = 0                    # 0 = Acoustic Grand Piano
    bass_program: Optional[int] = None         # si None, no hay 2ª voz

    # Tempo override (None = auto por tempo_bpm_for_meter)
    tempo_bpm: Optional[int] = None

    # Nombre de la nota de referencia ("La" = A4 = 69) - fijo a tradición
    reference_note_midi: int = 69              # A4


# ========== Builder ==========
class DictationMidiBuilder:
    def __init__(self, data: DictationInput):
        self.d = data
        self.events: list = []  # (abs_tick, priority, kind, channel, data1, data2)

        self.quarter_bpm = data.tempo_bpm or tempo_bpm_for_meter(
            data.time_sig_num, data.time_sig_den
        )
        self.tempo_us = int(60_000_000 / self.quarter_bpm)

        # Duración real del compás y del pulso en ticks
        # Compás = (num/den) * 4 * PPQ
        self.measure_ticks = int(4 * PPQ * data.time_sig_num / data.time_sig_den)

        # Pulso: negra con puntillo en compuesto, negra en binario
        is_compound = (data.time_sig_den == 8 and data.time_sig_num in (6, 9, 12)) or \
                      (data.time_sig_den == 16 and data.time_sig_num in (6, 9, 12))
        self.pulse_ticks = DOTTED_QUARTER if is_compound else QUARTER
        self.pulses_per_measure = self.measure_ticks // self.pulse_ticks

        # Canales melodía/bajo
        self.CH_MEL = 0
        self.CH_BASS = 1

    # -- helpers tiempo --
    def s_to_ticks(self, sec: float) -> int:
        return int(sec * PPQ * 1_000_000 / self.tempo_us)

    # -- registrar eventos --
    def _note(self, abs_tick, channel, note, velocity, duration):
        self.events.append((abs_tick, 1, 'note_on', channel, note, velocity))
        self.events.append((abs_tick + duration, 0, 'note_off', channel, note, 0))

    def _prog(self, abs_tick, channel, program):
        self.events.append((abs_tick, -1, 'program_change', channel, program, 0))

    def _cc(self, abs_tick, channel, cc_num, value):
        self.events.append((abs_tick, -1, 'control_change', channel, cc_num, value))

    # ---------- Bloque intro ----------
    def _reference_block(self, start):
        t = start
        note_dur = self.s_to_ticks(1.2)
        A = self.d.reference_note_midi
        T = self.d.tonic_midi
        M = self.measure_ticks

        self._note(t, self.CH_MEL, A, 88, note_dur); t += M
        self._note(t, self.CH_MEL, T, 88, note_dur); t += M
        self._note(t, self.CH_MEL, A, 88, note_dur); t += M

        # Acordes: 1 pulso cada uno, voz superior destacada
        chord_dur = self.pulse_ticks - SIXTEENTH
        VEL_TOP, VEL_INNER = 92, 65
        for ch in self.d.chord_progression:
            for n in ch['lower']:
                self._note(t, self.CH_MEL, n, VEL_INNER, chord_dur)
            self._note(t, self.CH_MEL, ch['top'], VEL_TOP, chord_dur)
            t += self.pulse_ticks
        return t - start

    # ---------- Indicadores de pase ----------
    def _section_indicator(self, start, play_ride):
        if not play_ride:
            return 0
        self._note(start, CH_DRUMS, PERC_SECTION, 100, self.s_to_ticks(0.35))
        return self.s_to_ticks(0.35) + self.s_to_ticks(1.2)

    def _rep_counter(self, start, n):
        t = start
        step = self.s_to_ticks(0.42)
        for _ in range(n):
            self._note(t, CH_DRUMS, PERC_COWBELL, 95, self.s_to_ticks(0.15))
            t += step
        return (t - start) + self.s_to_ticks(1.0)

    def _claqueta_previa(self, start):
        t = start
        for i in range(2):
            vel = 10 if i == 1 else 1   # acentuada=10, débil=1
            self._note(t, CH_DRUMS, PERC_SIDE_STICK, vel, SIXTEENTH)
            t += self.pulse_ticks
        return 2 * self.pulse_ticks

    def _subtle_click(self, start, duration):
        num_pulses = duration // self.pulse_ticks
        for p in range(num_pulses):
            is_downbeat = (p % self.pulses_per_measure == 0)
            vel = 19 if is_downbeat else 9
            self._note(start + p * self.pulse_ticks, CH_DRUMS,
                       PERC_SIDE_STICK, vel, SIXTEENTH)

    def _play_segment(self, start, segment, seg_len, with_bass=True):
        """Solo melodía (y 2ª voz si hay). Sin claqueta durante el dictado."""
        for off, note, dur in segment:
            beat_in_bar = off % self.measure_ticks
            vel = 100 if beat_in_bar == 0 else 72
            self._note(start + off, self.CH_MEL, note, vel, dur)
        # 2ª voz (bajo) si existe
        if with_bass and self.d.bass and self.d.bass_program is not None:
            bass_in_range = [(o, n, d) for (o, n, d) in self.d.bass
                             if start_off_in_segment(o, segment, seg_len)]
            for off, note, dur in bass_in_range:
                bar = off % self.measure_ticks
                vel = 90 if bar == 0 else 66
                self._note(start + off, self.CH_BASS, note, vel, dur)

    def _one_pass(self, start, section, rep_num, segment, seg_len, prev_section):
        play_ride = (section != prev_section)
        t = start
        t += self._section_indicator(t, play_ride)
        t += self._rep_counter(t, rep_num)
        t += self._claqueta_previa(t)
        self._play_segment(t, segment, seg_len)
        return t + seg_len

    def _gong(self, start):
        """Gong final ritual: G2 en canal 3 (reasignar Orchestral Kit en Logic)."""
        self._note(start, CH_GONG, GONG_NOTE, 65, self.s_to_ticks(5.0))

    # ---------- Build + save ----------
    def build(self, output_path: str):
        d = self.d
        M = self.measure_ticks
        DICT_LEN = d.num_measures * M

        # Melodía completa y fragmentos
        melody = d.melody
        first_half_end = (d.num_measures // 2) * M
        first_4 = [(o, n, du) for (o, n, du) in melody if o < first_half_end]
        first_4_len = first_half_end
        last_4 = [(o - first_half_end, n, du) for (o, n, du) in melody if o >= first_half_end]
        last_4_len = DICT_LEN - first_half_end

        # program changes
        self._prog(0, self.CH_MEL, d.melody_program)
        if d.bass_program is not None:
            self._prog(0, self.CH_BASS, d.bass_program)
        self._prog(0, CH_GONG, PROG_GONG)  # Orchestra Hit (usuario reasigna Orchestral Kit)

        # Batería a -4 dB aprox vía CC7 (channel volume)
        # val = 127 * 10^(dB/40)  ->  -4 dB ≈ 101
        self._cc(0, CH_DRUMS, 7, 101)

        # Medio compás de silencio al principio
        current = M // 2

        # Bloque intro x2
        for i in range(2):
            current += self._reference_block(current)
            current += (2 if i == 0 else 4) * M

        prev_sec = None

        # entero 1
        current = self._one_pass(current, 'entero', 1, melody, DICT_LEN, prev_sec)
        prev_sec = 'entero'
        current += 8 * M

        # primeros x4
        for i in range(1, 5):
            current = self._one_pass(current, 'primeros', i, first_4, first_4_len, prev_sec)
            prev_sec = 'primeros'
            current += 8 * M

        # entero 2
        current = self._one_pass(current, 'entero', 2, melody, DICT_LEN, prev_sec)
        prev_sec = 'entero'
        current += 8 * M

        # últimos x4
        for i in range(1, 5):
            current = self._one_pass(current, 'ultimos', i, last_4, last_4_len, prev_sec)
            prev_sec = 'ultimos'
            current += 8 * M

        # enteros 3 y 4
        current = self._one_pass(current, 'entero', 3, melody, DICT_LEN, prev_sec)
        prev_sec = 'entero'
        current += 8 * M
        current = self._one_pass(current, 'entero', 4, melody, DICT_LEN, prev_sec)

        # Gong final ritual: 1 compás de silencio y un único golpe
        current += M
        self._gong(current)
        current += self.s_to_ticks(5.0)

        # --- Escritura ---
        self.events.sort(key=lambda e: (e[0], e[1]))
        mid = MidiFile(type=0, ticks_per_beat=PPQ)
        track = MidiTrack(); mid.tracks.append(track)
        track.append(MetaMessage('track_name', name='Dictado Didáctico', time=0))
        track.append(MetaMessage('set_tempo', tempo=self.tempo_us, time=0))
        track.append(MetaMessage('time_signature',
                                 numerator=d.time_sig_num, denominator=d.time_sig_den,
                                 clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
        track.append(MetaMessage('key_signature', key=d.key_sig_label, time=0))

        prev = 0
        for abs_t, _prio, kind, ch, d1, d2 in self.events:
            dt = abs_t - prev; prev = abs_t
            if kind == 'note_on':
                track.append(Message('note_on', note=d1, velocity=d2, channel=ch, time=dt))
            elif kind == 'note_off':
                track.append(Message('note_off', note=d1, velocity=d2, channel=ch, time=dt))
            elif kind == 'program_change':
                track.append(Message('program_change', program=d1, channel=ch, time=dt))
            elif kind == 'control_change':
                track.append(Message('control_change', control=d1, value=d2, channel=ch, time=dt))
        track.append(MetaMessage('end_of_track', time=0))
        mid.save(output_path)
        return output_path


def start_off_in_segment(off, segment, seg_len):
    """Helper: true si el offset cae dentro del segmento."""
    return 0 <= off < seg_len


# ========== Construcción automática de acordes i-iv-V-i ==========
def build_chord_progression(tonic_pc: int, mode: str):
    """
    Devuelve acordes i-iv-V-i (menor) o I-IV-V-I (mayor), con voicing:
    bajo en octava 3 + triada cerrada en octava 3-4, y voz superior haciendo
    tónica - tónica - sensible - tónica (para que la sensible resuelva a tónica).

    tonic_pc: pitch class (0=C, 2=D, 5=F, 7=G, ...) de la tónica
    mode: 'major' o 'minor'
    """
    # Escala natural por modo (grados)
    if mode == 'minor':
        scale = [0, 2, 3, 5, 7, 8, 10]          # menor natural
        chord_qualities = {
            'i':  (0, 3, 7),                    # Gm: 1-b3-5
            'iv': (5, 8, 12),                   # Cm: 4-b6-8  (desde tonic_pc)
            'V':  (7, 11, 14),                  # V mayor con sensible (7 + 4st = mayor)
        }
        leading_tone = 11                       # sensible = b7 raised = 11 semitonos desde tónica
    else:  # major
        chord_qualities = {
            'I':  (0, 4, 7),
            'IV': (5, 9, 12),
            'V':  (7, 11, 14),
        }
        leading_tone = 11

    # Octava 3 para el bajo
    bass_base = 36 + tonic_pc  # C3=48; MIDI 48 es C3. Pero C2=36. Quiero octava 3 = C3=48.
    # Ajuste: bass octave 3 (MIDI 48..59)
    bass_base = 48 + tonic_pc if tonic_pc < 12 else 48 + (tonic_pc % 12)
    # Nota tónica en octava 4 para la voz superior
    top_tonic = 60 + tonic_pc if tonic_pc <= 7 else 48 + tonic_pc  # G4 = 67 para G

    # Para evitar líos: trabajamos en semitonos desde tonic_pc y añadimos octavas.
    def mk_chord(root_offset, intervals, top_note):
        root = 48 + ((tonic_pc + root_offset) % 12)        # octava 3
        # Ajuste para que iv y V no se disparen hacia arriba
        if root > bass_base + 5:                           # si el root queda muy arriba, -12
            root -= 12
        n1 = root + intervals[0]                           # ya es root
        n2 = root + intervals[1]
        n3 = root + intervals[2]
        # Reorganizar para disposición cerrada y llevar 'top_note' como voz superior
        lower = sorted([root, n2, n3])
        # Ajustar n3 para quedar bajo top_note
        while lower[-1] >= top_note:
            lower[-1] -= 12
        lower = sorted([lower[0], lower[1], lower[2]])
        return {'lower': lower[:3], 'top': top_note}

    if mode == 'minor':
        # Voicing "tónica - tónica - sensible - tónica" en voz superior
        sensible = 48 + ((tonic_pc + 11) % 12)               # sensible octava 3
        while sensible < top_tonic - 12: sensible += 12
        while sensible > top_tonic + 1: sensible -= 12
        # ajustamos sensible a quedar pegado a la tónica superior
        sensible = top_tonic - 1

        chords = [
            mk_chord(0, (0, 3, 7), top_tonic),               # i
            mk_chord(5, (0, 3, 7), top_tonic),               # iv (minor IV en menor natural)
            mk_chord(7, (0, 4, 7), sensible),                # V mayor -> voz superior = sensible
            mk_chord(0, (0, 3, 7), top_tonic),               # i
        ]
    else:
        sensible = top_tonic - 1
        chords = [
            mk_chord(0, (0, 4, 7), top_tonic),
            mk_chord(5, (0, 4, 7), top_tonic),
            mk_chord(7, (0, 4, 7), sensible),
            mk_chord(0, (0, 4, 7), top_tonic),
        ]
    return chords
