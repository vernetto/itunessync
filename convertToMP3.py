from gtts import gTTS

# Leggi file
with open("D:\\pierre\\pvtranslate\\inputfiles\\erhardloretan\\libroerhardloretan.txt", "r", encoding="utf-8") as f:
    text = f.read()

# Genera audio in francese
tts = gTTS(text=text, lang="fr")

# Salva MP3
tts.save("output.mp3")
