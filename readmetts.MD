edge-tts --voice de-DE-ConradNeural -f allkafka.txt --write-media allkafka.mp3
ffmpeg -i pippo_full.mp3 -f segment -segment_time 1800 -c copy pippo_%03d.mp3


de-DE-KatjaNeural
de-DE-AmalaNeural
de-DE-SeraphinaMultilingualNeural

ru-RU-SvetlanaNeural
ru-RU-DariyaNeural

it-IT-ElsaNeural
it-IT-IsabellaNeural

en-US-JennyNeural
en-US-AriaNeural

en-IN-NeerjaNeural
en-IN-NeerjaExpressiveNeural

