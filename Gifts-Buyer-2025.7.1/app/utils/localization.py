import i18n
from pathlib import Path

LOCALES_DIR = Path(__file__).parent.parent.parent / 'locales'

class LocalizationManager:
    def __init__(self):
        self._initialize_i18n()

    @staticmethod
    def _initialize_i18n() -> None:
        i18n.load_path.append(str(LOCALES_DIR))
        i18n.set('filename_format', '{locale}.{format}')
        i18n.set('file_format', 'yml')
        i18n.set('skip_locale_root_data', True)
        i18n.set('fallback', 'en')
        i18n.set('available_locales', ['ru', 'en'])

    def set_locale(self, locale: str) -> None:
        i18n.set('locale', locale)

    @staticmethod
    def translate(key: str, **kwargs) -> str:
        locale = kwargs.pop('locale', i18n.get('locale'))
        translated_text = i18n.t(key, locale=locale)
        if kwargs:
            try:
                translated_text = translated_text.format(**kwargs)
            except Exception as e:
                print(f"Error formatting translation: {e}")
        return translated_text

    def get_display_name(self, locale: str) -> str:
        # Return a display name for the locale, e.g. "Русский" for "ru"
        display_names = {
            'ru': 'Русский',
            'en': 'English'
        }
        return display_names.get(locale.lower(), locale)

    def get_language_code(self, locale: str) -> str:
        # Return a language code for the locale, e.g. "ru" for "ru"
        language_codes = {
            'ru': 'ru',
            'en': 'en'
        }
        return language_codes.get(locale.lower(), locale)

localization = LocalizationManager()
