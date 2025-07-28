from googletrans import Translator

translator = Translator()

def translate_en_to_tr(text: str) -> str:
    try:
        res = translator.translate(text, src='en', dest='tr')
        return res.text
    except Exception as e:
        return f"[Çeviri Hatası: {e}]"
