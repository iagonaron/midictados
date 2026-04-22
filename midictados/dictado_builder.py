"""
Constructor de MIDI pedagógico para dictados musicales.

Consignas 1 voz:
  - Tempo por convención: compuesto (6/8, 9/8, 12/8) = 50 bpm; binario = 60 bpm.
  - Silencio inicial, intro x2 (La-Tónica-La-Acordes i-iv-V-i).
  - entero x1 → primeros x4 → entero → últimos x4 → entero x2.
  - Cencerros solo antes de frases (no en enteros).
  - Ride solo en cambio de sección.
  - Gap reducido (4M) tras el primer entero.
  - Gong final en canal 3.

Consignas 2 voces (si bass_program != None y bass!=[]):
  - Tras intro x2 y primer entero: REGALO (una sola vez).
      Lágrima (bell tree, altura indeterminada) → La4 + 1ª nota clave de sol →
      La3 + 1ª nota clave de fa.
  - Primeros x6 y últimos x6: 3 reps destacando melodía (bajo muy atenuado) +
      3 reps destacando bajo (melodía muy atenuada).
  - Ride al cambiar de foco (reset de cencerros: nunca >3 seguidos).
"""
from dataclasses import dataclass
from typing import Optional
import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage

# ========== Ticks ==========
PPQ = 480
QUARTER = PPQ
EIGHTH = PPQ // 2
SIXTEENTH = PPQ // 4
DOTTED_QUARTER = QUARTER + EIGHTH
DOTTED_EIGHTH = EIGHTH + SIXTEENTH

# ========== Percusión (canal 10) ==========
CH_DRUMS = 9
PERC_SIDE_STICK = 37
PERC_SNARE = 38
PERC_BASS_DRUM = 36
PERC_CRASH = 49
PERC_COWBELL = 56
PERC_SECTION = 59        # Ride Cymbal 2
PERC_TRIANGLE = 81       # Open Triangle (GM1 seguro) — "lágrima" del regalo 2 voces

# ========== Gong (canal 3) ==========
CH_GONG = 2
PROG_GONG = 47           # placeholder; usuario asigna Orchestral Kit en Logic
GONG_NOTE = 55           # G2 en Logic = gong en Orchestral Kit

# ========== Sparkle / Regalo 2 voces (canal 4) ==========
CH_SPARKLE = 3
PROG_SPARKLE = 9         # Glockenspiel (GM1 — fijo en Logic, timbre "estrellitas")


def tempo_bpm_for_meter(num: int, den: int, two_voice: bool = False) -> int:
    """
    Tempo por convención:
      - 1 voz: compuesto 50 / simple 60
      - 2 voces: compuesto 55 / simple 65 (para acercar la duración total a ~10 min)
    """
    is_compound = (den == 8 and num in (6, 9, 12)) or (den == 16 and num in (6, 9, 12))
    if two_voice:
        return 55 if is_compound else 65
    return 50 if is_compound else 60


@dataclass
class DictationInput:
    melody: list
    num_measures: int
    time_sig_num: int
    time_sig_den: int
    key_sig_label: str
    tonic_midi: int
    chord_progression: list
    bass: Optional[list] = None
    melody_program: int = 0
    bass_program: Optional[int] = None
    tempo_bpm: Optional[int] = None
    reference_note_midi: int = 69  # A4


class DictationMidiBuilder:
    def __init__(self, data: DictationInput):
        self.d = data
        self.events: list = []

        self.two_voice = (data.bass is not None and len(data.bass) > 0
                          and data.bass_program is not None)

        self.quarter_bpm = data.tempo_bpm or tempo_bpm_for_meter(
            data.time_sig_num, data.time_sig_den, two_voice=self.two_voice
        )
        self.tempo_us = int(60_000_000 / self.quarter_bpm)
        self.measure_ticks = int(4 * PPQ * data.time_sig_num / data.time_sig_den)

        is_compound = (data.time_sig_den == 8 and data.time_sig_num in (6, 9, 12)) or \
                      (data.time_sig_den == 16 and data.time_sig_num in (6, 9, 12))
        self.pulse_ticks = DOTTED_QUARTER if is_compound else QUARTER
        self.pulses_per_measure = self.measure_ticks // self.pulse_ticks

        self.CH_MEL = 0
        self.CH_BASS = 1

    def s_to_ticks(self, sec: float) -> int:
        return int(sec * PPQ * 1_000_000 / self.tempo_us)

    # ---------- Event helpers ----------
    def _note(self, abs_tick, channel, note, velocity, duration):
        self.events.append((abs_tick, 1, 'note_on', channel, note, velocity))
        self.events.append((abs_tick + duration, 0, 'note_off', channel, note, 0))

    def _prog(self, abs_tick, channel, program):
        self.events.append((abs_tick, -1, 'program_change', channel, program, 0))

    def _cc(self, abs_tick, channel, cc_num, value):
        self.events.append((abs_tick, -1, 'control_change', channel, cc_num, value))

    # ---------- Intro ----------
    def _reference_block(self, start):
        t = start
        note_dur = self.s_to_ticks(1.2)
        A = self.d.reference_note_midi
        T = self.d.tonic_midi
        M = self.measure_ticks

        self._note(t, self.CH_MEL, A, 88, note_dur); t += M
        self._note(t, self.CH_MEL, T, 88, note_dur); t += M
        self._note(t, self.CH_MEL, A, 88, note_dur); t += M

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
            vel = 10 if i == 1 else 1
            self._note(t, CH_DRUMS, PERC_SIDE_STICK, vel, SIXTEENTH)
            t += self.pulse_ticks
        return 2 * self.pulse_ticks

    # ---------- Regalo 2 voces ----------
    def _lagrima(self, start):
        """
        Arpegio mayor ascendente (Do-Mi-Sol-Do) en octava 7, con Glockenspiel.
        Efecto tipo "llamada de supermercado/estrellitas" — brillante pero no invasivo.
        """
        t = start
        step = self.s_to_ticks(0.22)
        notes = [96, 100, 103, 108]     # C7, E7, G7, C8
        vels  = [34, 32, 32, 40]        # velocidades bajas (ajuste fino de Iago)
        note_dur = self.s_to_ticks(1.2) # se solapan para que "brille"
        for n, v in zip(notes, vels):
            self._note(t, CH_SPARKLE, n, v, note_dur)
            t += step
        return self.measure_ticks  # 1 compás completo para el efecto + respiración

    def _referencia_voz(self, start, ref_note, first_note, channel):
        """La (referencia) + 1ª nota de la voz, alineadas a compás (como intro La-Tónica)."""
        M = self.measure_ticks
        note_dur = self.s_to_ticks(1.2)
        self._note(start, channel, ref_note, 92, note_dur)
        self._note(start + M, channel, first_note, 92, note_dur)
        return 2 * M

    def _regalo(self, start, first_treble, first_bass):
        """Lágrima + La4+1ª treble + La3+1ª bass. Suena solo al principio."""
        t = start
        t += self._lagrima(t)
        t += self._referencia_voz(t, 69, first_treble, self.CH_MEL)   # La4 + 1ª clave de sol
        t += self._referencia_voz(t, 57, first_bass, self.CH_BASS)    # La3 + 1ª clave de fa
        return t - start

    # ---------- Pases ----------
    def _play_segment(self, start, mel_seg, bass_seg, focus=None):
        """
        focus: None = equilibrio normal.
               'treble' = bajo muy atenuado (foco en melodía).
               'bass'   = melodía muy atenuada (foco en bajo).
        """
        for off, note, dur in mel_seg:
            beat_in_bar = off % self.measure_ticks
            if focus == 'bass':
                vel = 35 if beat_in_bar == 0 else 24
            else:
                vel = 100 if beat_in_bar == 0 else 72
            self._note(start + off, self.CH_MEL, note, vel, dur)
        if bass_seg and self.d.bass_program is not None:
            for off, note, dur in bass_seg:
                bar = off % self.measure_ticks
                if focus == 'treble':
                    vel = 35 if bar == 0 else 24
                else:
                    vel = 90 if bar == 0 else 66
                self._note(start + off, self.CH_BASS, note, vel, dur)

    def _one_pass(self, start, section, rep_num, mel_seg, bass_seg, seg_len,
                  prev_section, focus=None):
        play_ride = (section != prev_section)
        t = start
        t += self._section_indicator(t, play_ride)
        if section != 'entero':
            t += self._rep_counter(t, rep_num)
        t += self._claqueta_previa(t)
        self._play_segment(t, mel_seg, bass_seg, focus=focus)
        return t + seg_len

    # ---------- Final ----------
    def _gong(self, start):
        self._note(start, CH_GONG, GONG_NOTE, 85, self.s_to_ticks(5.0))

    # ---------- Build ----------
    def build(self, output_path: str):
        d = self.d
        M = self.measure_ticks
        DICT_LEN = d.num_measures * M

        two_voice = self.two_voice

        # Segmentos: melodía y bajo. Últimos shifteados a offset 0.
        mel_full = d.melody
        bass_full = d.bass or []
        half = (d.num_measures // 2) * M
        mel_first = [(o, n, du) for (o, n, du) in mel_full if o < half]
        mel_last = [(o - half, n, du) for (o, n, du) in mel_full if o >= half]
        bass_first = [(o, n, du) for (o, n, du) in bass_full if o < half]
        bass_last = [(o - half, n, du) for (o, n, du) in bass_full if o >= half]
        first_len = half
        last_len = DICT_LEN - half

        # Program changes
        self._prog(0, self.CH_MEL, d.melody_program)
        if d.bass_program is not None:
            self._prog(0, self.CH_BASS, d.bass_program)
        self._prog(0, CH_GONG, PROG_GONG)
        if self.two_voice:
            self._prog(0, CH_SPARKLE, PROG_SPARKLE)
            self._cc(0, CH_SPARKLE, 7, 85)  # Volumen de canal del regalo (~67%)

        # Batería -4 dB
        self._cc(0, CH_DRUMS, 7, 101)

        # Silencio inicial
        current = M // 2

        # Intro x2
        for i in range(2):
            current += self._reference_block(current)
            current += (2 if i == 0 else 3) * M

        prev_sec = None

        if two_voice:
            # Entero #1
            current = self._one_pass(current, 'entero', 1, mel_full, bass_full,
                                     DICT_LEN, prev_sec)
            prev_sec = 'entero'
            current += 2 * M  # respiración antes del regalo

            # REGALO (una sola vez)
            first_treble = mel_full[0][1] if mel_full else 67
            first_bass = bass_full[0][1] if bass_full else 55
            current += self._regalo(current, first_treble, first_bass)
            current += 1 * M  # respiración
            prev_sec = 'regalo'  # fuerza ride al entrar a primeros_treble

            # Primeros x6: 3 treble-focused + 3 bass-focused
            for rep in range(1, 4):
                current = self._one_pass(current, 'primeros_treble', rep,
                                         mel_first, bass_first, first_len,
                                         prev_sec, focus='treble')
                prev_sec = 'primeros_treble'
                current += 6 * M
            for rep in range(1, 4):
                current = self._one_pass(current, 'primeros_bass', rep,
                                         mel_first, bass_first, first_len,
                                         prev_sec, focus='bass')
                prev_sec = 'primeros_bass'
                current += 6 * M

            # Entero #2
            current = self._one_pass(current, 'entero', 2, mel_full, bass_full,
                                     DICT_LEN, prev_sec)
            prev_sec = 'entero'
            current += 6 * M

            # Últimos x6
            for rep in range(1, 4):
                current = self._one_pass(current, 'ultimos_treble', rep,
                                         mel_last, bass_last, last_len,
                                         prev_sec, focus='treble')
                prev_sec = 'ultimos_treble'
                current += 6 * M
            for rep in range(1, 4):
                current = self._one_pass(current, 'ultimos_bass', rep,
                                         mel_last, bass_last, last_len,
                                         prev_sec, focus='bass')
                prev_sec = 'ultimos_bass'
                current += 6 * M

            # Enteros #3 y #4
            current = self._one_pass(current, 'entero', 3, mel_full, bass_full,
                                     DICT_LEN, prev_sec)
            prev_sec = 'entero'
            current += 6 * M
            current = self._one_pass(current, 'entero', 4, mel_full, bass_full,
                                     DICT_LEN, prev_sec)
        else:
            # 1 voz (flujo clásico)
            current = self._one_pass(current, 'entero', 1, mel_full, [], DICT_LEN, prev_sec)
            prev_sec = 'entero'
            current += 4 * M

            for i in range(1, 5):
                current = self._one_pass(current, 'primeros', i, mel_first, [],
                                         first_len, prev_sec)
                prev_sec = 'primeros'
                current += 6 * M

            current = self._one_pass(current, 'entero', 2, mel_full, [], DICT_LEN, prev_sec)
            prev_sec = 'entero'
            current += 6 * M

            for i in range(1, 5):
                current = self._one_pass(current, 'ultimos', i, mel_last, [],
                                         last_len, prev_sec)
                prev_sec = 'ultimos'
                current += 6 * M

            current = self._one_pass(current, 'entero', 3, mel_full, [], DICT_LEN, prev_sec)
            prev_sec = 'entero'
            current += 6 * M
            current = self._one_pass(current, 'entero', 4, mel_full, [], DICT_LEN, prev_sec)

        # Gong final
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
    """Legacy, no usado actualmente."""
    return 0 <= off < seg_len


# ========== Construcción automática de acordes i-iv-V-i ==========
def build_chord_progression(tonic_pc: int, mode: str):
    """
    Devuelve acordes i-iv-V-i (menor) o I-IV-V-I (mayor), con la voz superior
    haciendo tónica - tónica - sensible - tónica.
    """
    bass_base = 48 + tonic_pc if tonic_pc < 12 else 48 + (tonic_pc % 12)
    top_tonic = 60 + tonic_pc if tonic_pc <= 7 else 48 + tonic_pc

    def mk_chord(root_offset, intervals, top_note):
        root = 48 + ((tonic_pc + root_offset) % 12)
        if root > bass_base + 5:
            root -= 12
        n2 = root + intervals[1]
        n3 = root + intervals[2]
        lower = sorted([root, n2, n3])
        while lower[-1] >= top_note:
            lower[-1] -= 12
        lower = sorted(lower)
        return {'lower': lower[:3], 'top': top_note}

    if mode == 'minor':
        sensible = top_tonic - 1
        chords = [
            mk_chord(0, (0, 3, 7), top_tonic),
            mk_chord(5, (0, 3, 7), top_tonic),
            mk_chord(7, (0, 4, 7), sensible),
            mk_chord(0, (0, 3, 7), top_tonic),
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
