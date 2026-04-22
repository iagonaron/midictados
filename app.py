"""
MiDictados — herramienta pedagógica para generar MIDIs de dictado musical
a partir de un MusicXML.

Autor: Iago (Conservatorio de Música de A Coruña)
"""
import os
import tempfile
import streamlit as st

from musicxml_parser import parse_musicxml, detect_params
from dictado_builder import DictationMidiBuilder, tempo_bpm_for_meter

st.set_page_config(page_title="MiDictados", page_icon="🎼", layout="centered")

st.title("🎼 MiDictados")
st.caption("Generador de MIDIs pedagógicos para dictado musical desde MusicXML.")


def midi_to_name(m: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[m % 12]}{m // 12 - 1}"

# -------------------- General MIDI programs --------------------
GM_PROGRAMS = {
    "Piano acústico": 0, "Piano brillante": 1, "Piano eléctrico 1": 4,
    "Clavicémbalo": 6, "Celesta": 8, "Vibráfono": 11, "Marimba": 12,
    "Órgano de iglesia": 19, "Guitarra acústica (nylon)": 24,
    "Guitarra acústica (acero)": 25, "Bajo acústico": 32, "Bajo eléctrico (finger)": 33,
    "Contrabajo": 43, "Violín": 40, "Viola": 41, "Violoncello": 42,
    "Pizzicato de cuerdas": 45, "Arpa": 46, "Cuerdas ensemble 1": 48,
    "Coro aahs": 52, "Trompeta": 56, "Trombón": 57, "Tuba": 58,
    "Trompa": 60, "Sección de metales": 61, "Saxofón soprano": 64,
    "Saxofón alto": 65, "Saxofón tenor": 66, "Saxofón barítono": 67,
    "Oboe": 68, "Fagot": 70, "Clarinete": 71, "Flauta": 73,
    "Flauta dulce": 74, "Flauta pan": 75, "Sinusoide (lead)": 80,
}

# -------------------- Carga de archivo --------------------
uploaded = st.file_uploader("Arrastra o sube un archivo MusicXML", type=["xml", "musicxml", "mxl"])

if uploaded is None:
    st.info("Sube un MusicXML para empezar. Se detectará tonalidad, compás y tónica automáticamente.")
    st.stop()

# Guardar archivo temporal
with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded.name)[1]) as tmp:
    tmp.write(uploaded.read())
    xml_path = tmp.name

# -------------------- Detección automática --------------------
try:
    detected = detect_params(xml_path)
except Exception as e:
    st.error(f"No se pudo analizar el archivo: {e}")
    st.stop()

st.success(
    f"Detectado: compás {detected['time_sig_num']}/{detected['time_sig_den']}, "
    f"tonalidad {detected['key_label']}, "
    f"tónica {midi_to_name(detected['tonic_midi'])} (MIDI {detected['tonic_midi']})"
)

# -------------------- Configuración --------------------
st.subheader("Parámetros")

col1, col2 = st.columns(2)
with col1:
    num = st.number_input("Compás (numerador)", min_value=1, max_value=16,
                          value=detected['time_sig_num'])
    key_label = st.text_input("Tonalidad (ej. Gm, C, F, Dm)", value=detected['key_label'])
with col2:
    den = st.selectbox("Compás (denominador)", [2, 4, 8, 16],
                       index=[2, 4, 8, 16].index(detected['time_sig_den']))
    tonic_midi = st.number_input("Tónica MIDI", min_value=0, max_value=127,
                                  value=detected['tonic_midi'])

default_tempo = tempo_bpm_for_meter(num, den)
tempo_bpm = st.slider("Tempo (bpm)", 30, 120, default_tempo,
                      help="Convención: compuesto=50, binario=60")

st.subheader("Instrumentos")

inst_names = list(GM_PROGRAMS.keys())
mel_name = st.selectbox("Voz superior (clave de sol)", inst_names,
                        index=inst_names.index("Piano acústico"))
melody_program = GM_PROGRAMS[mel_name]

use_two = st.checkbox("Incluir 2ª voz (clave de fa)",
                      value=False,
                      disabled=detected['num_parts'] < 2,
                      help="Solo disponible si el MusicXML tiene ≥ 2 partes.")
bass_program = None
if use_two:
    bass_name = st.selectbox("Voz inferior (clave de fa)", inst_names,
                             index=inst_names.index("Violoncello"))
    bass_program = GM_PROGRAMS[bass_name]

# -------------------- Generar --------------------
if st.button("🎹 Generar MIDI", type="primary"):
    try:
        data = parse_musicxml(
            xml_path,
            melody_program=melody_program,
            bass_program=bass_program,
            tempo_bpm=tempo_bpm,
            force_tonic_midi=int(tonic_midi),
            force_key_label=key_label,
            force_time_sig=(int(num), int(den)),
            use_two_voices=use_two,
        )
        out_path = os.path.join(tempfile.gettempdir(), "midictados_output.mid")
        DictationMidiBuilder(data).build(out_path)
        with open(out_path, "rb") as f:
            st.download_button(
                "⬇️ Descargar dictado.mid",
                data=f.read(),
                file_name=f"dictado_{data.key_sig_label}_{num}-{den}.mid",
                mime="audio/midi",
            )
        st.success(f"Generado: {data.num_measures} compases, "
                   f"{data.time_sig_num}/{data.time_sig_den}, "
                   f"{data.key_sig_label}, tempo {tempo_bpm} bpm.")
    except Exception as e:
        st.error(f"Error al generar: {e}")
        st.exception(e)
