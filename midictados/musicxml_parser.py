"""
MiDictados - Parser de MusicXML.

Convierte un archivo MusicXML en la estructura DictationInput que
consume dictado_builder.py.
"""
from typing import Optional
from dictado_builder import DictationInput, build_chord_progression, PPQ

# music21 se importa de forma diferida (lazy) porque tarda 30-60s en cargar.
# No queremos bloquear el arranque de la app; solo se necesita al parsear.
_m21 = None
def _get_m21():
    global _m21
    if _m21 is None:
        from music21 import converter, note, chord, key, meter, pitch
        _m21 = dict(converter=converter, note=note, chord=chord,
                    key=key, meter=meter, pitch=pitch)
    return _m21


def _dur_to_ticks(ql: float) -> int:
    """Quarter-length (music21) → ticks con PPQ=480."""
    return int(round(ql * PPQ))


def parse_musicxml(
    path: str,
    melody_program: int = 0,
    bass_program: Optional[int] = None,
    tempo_bpm: Optional[int] = None,
    force_tonic_midi: Optional[int] = None,
    force_key_label: Optional[str] = None,
    force_time_sig: Optional[tuple] = None,
    use_two_voices: bool = False,
) -> DictationInput:
    """
    Extrae:
      - melody: eventos (offset_ticks, midi_note, dur_ticks) de la voz superior
      - bass: ídem para la 2ª voz si use_two_voices=True
      - num_measures, time_sig, key, tonic
    """
    m21 = _get_m21()
    converter = m21['converter']; meter = m21['meter']; pitch = m21['pitch']
    score = converter.parse(path)

    # --- Compás ---
    ts_list = score.recurse().getElementsByClass(meter.TimeSignature)
    if ts_list:
        num, den = ts_list[0].numerator, ts_list[0].denominator
    else:
        num, den = 4, 4
    if force_time_sig:
        num, den = force_time_sig

    # --- Tonalidad ---
    key_label = force_key_label
    tonic_midi = force_tonic_midi
    if key_label is None or tonic_midi is None:
        k = score.analyze('key')
        # mido admite: 'C','Cm','D','Dm',...
        detected_label = k.tonic.name.replace('-', 'b') + ('m' if k.mode == 'minor' else '')
        if key_label is None:
            key_label = detected_label
        if tonic_midi is None:
            # Preferencia: última nota del score (práctica musical)
            last = _last_melodic_note(score)
            if last is not None:
                tonic_midi = last.pitch.midi
            else:
                tonic_midi = pitch.Pitch(k.tonic.name + '4').midi

    # --- Partes ---
    parts = list(score.parts)
    melody_part = parts[0] if parts else score
    bass_part = parts[1] if len(parts) > 1 and use_two_voices else None

    melody_events = _part_to_events(melody_part)
    bass_events = _part_to_events(bass_part) if bass_part is not None else None

    # Nº de compases: del último offset + duración
    if melody_events:
        last_off, _, last_dur = melody_events[-1]
        total_ticks = last_off + last_dur
    else:
        total_ticks = 0
    measure_ticks = int(4 * PPQ * num / den)
    num_measures = max(1, -(-total_ticks // measure_ticks))  # ceil

    # --- Progresión de acordes i-iv-V-i ---
    mode = 'minor' if key_label.endswith('m') else 'major'
    tonic_pc = tonic_midi % 12
    progression = build_chord_progression(tonic_pc, mode)

    return DictationInput(
        melody=melody_events,
        num_measures=num_measures,
        time_sig_num=num,
        time_sig_den=den,
        key_sig_label=key_label,
        tonic_midi=tonic_midi,
        chord_progression=progression,
        bass=bass_events,
        melody_program=melody_program,
        bass_program=bass_program if use_two_voices else None,
        tempo_bpm=tempo_bpm,
    )


def _part_to_events(part) -> list:
    """Stream → [(offset_ticks, midi_note, dur_ticks)]. Silencios omitidos."""
    m21 = _get_m21()
    note, chord = m21['note'], m21['chord']
    events = []
    flat = part.flatten().notesAndRests
    for el in flat:
        off = _dur_to_ticks(float(el.offset))
        dur = _dur_to_ticks(float(el.duration.quarterLength))
        if isinstance(el, note.Note):
            events.append((off, el.pitch.midi, dur))
        elif isinstance(el, chord.Chord):
            # Tomar la nota más aguda (voz superior)
            top = max(el.pitches, key=lambda p: p.midi)
            events.append((off, top.midi, dur))
        # Silencios: no se añaden, el espacio queda implícito por los offsets
    return events


def _last_melodic_note(score):
    """Devuelve la última note.Note del score (para validar tónica)."""
    note = _get_m21()['note']
    notes = list(score.recurse().getElementsByClass(note.Note))
    return notes[-1] if notes else None


def detect_params(path: str) -> dict:
    """Devuelve solo los parámetros detectados (sin construir DictationInput)."""
    m21 = _get_m21()
    converter = m21['converter']; meter = m21['meter']; pitch = m21['pitch']
    score = converter.parse(path)
    ts_list = score.recurse().getElementsByClass(meter.TimeSignature)
    num, den = (ts_list[0].numerator, ts_list[0].denominator) if ts_list else (4, 4)
    k = score.analyze('key')
    key_label = k.tonic.name.replace('-', 'b') + ('m' if k.mode == 'minor' else '')
    last = _last_melodic_note(score)
    tonic_midi = last.pitch.midi if last is not None else pitch.Pitch(k.tonic.name + '4').midi
    parts = list(score.parts)
    return {
        'time_sig_num': num,
        'time_sig_den': den,
        'key_label': key_label,
        'tonic_midi': tonic_midi,
        'num_parts': len(parts),
    }
