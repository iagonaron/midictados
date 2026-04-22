# MiDictados

Herramienta web para generar MIDIs pedagógicos de dictado musical a partir de un archivo MusicXML.

Pensado para clase de Lenguaje Musical: a partir de una partitura en MusicXML, produce un audio MIDI con la estructura didáctica completa (tonos de referencia, acordes tonales, pase entero, fragmentos repetidos, claqueta, cencerros-contador, etc.).

## Estructura generada

Para cada dictado, el MIDI contiene:

1. 1 compás de silencio inicial.
2. **Bloque de introducción (x2):** La de referencia – tónica – La – progresión i–iv–V–i.
3. Entero (×1) → primeros 4 compases (×4) → entero → últimos 4 compases (×4) → entero (×2).
4. Antes de cada pase: indicador de sección (ride, solo al cambiar de sección), cencerros contando la repetición, claqueta previa (2 pulsos).
5. Durante cada pase: click sutil con acento en downbeat.
6. Final: "badum-tss" rápido (snare–snare–bombo+crash).

Convención de tempo: compuesto (6/8, 9/8, 12/8) = 50 bpm · binario = 60 bpm.

## Uso local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Despliegue en Streamlit Community Cloud

1. Crea un repo nuevo en GitHub (por ejemplo, `midictados`).
2. Sube estos archivos al repo.
3. Ve a [share.streamlit.io](https://share.streamlit.io), conecta tu GitHub y elige el repo.
4. Archivo principal: `app.py`. Versión de Python: 3.11.
5. Deploy.

## Archivos

- `app.py` — interfaz Streamlit.
- `musicxml_parser.py` — parser de MusicXML (music21).
- `dictado_builder.py` — constructor pedagógico del MIDI (mido).
- `requirements.txt` — dependencias.
