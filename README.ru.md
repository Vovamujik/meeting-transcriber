# meeting-transcriber

[English](README.md) · **Русский**

Локальная расшифровка записей встреч в текст с таймкодами и разделением по спикерам. Результат готов к тому, чтобы закинуть его в ChatGPT, Claude или любую другую нейронку. Под капотом [WhisperX](https://github.com/m-bain/whisperX) (распознавание речи и выравнивание по словам) и [pyannote](https://github.com/pyannote/pyannote-audio) (кто когда говорит).

Работает как консольная утилита и как [Agent Skill](https://agentskills.io) для Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI и OpenCode. Можно просто попросить агента: «расшифруй созвон и выпиши задачи».

```
Файл: planning.m4a
Длительность: 00:42:13
Язык: ru
Спикеров: 3
Расшифровка автоматическая: возможны ошибки в словах и в определении спикеров.

[00:00:03] Спикер 1: Всем привет. Давайте начнём с релиза мобильного приложения.

[00:00:09] Спикер 2: Закрыли двенадцать задач, осталось три бага в оплате.

[00:00:16] Спикер 1: Успеем до пятницы?
```

- **Приватно.** Аудио не покидает компьютер. Из сети при первом запуске скачиваются только веса моделей; телеметрия pyannote отключена.
- **Спикеры привязаны к словам.** Каждое слово выравнивается по времени и получает своего спикера, поэтому реплики режутся правильно, даже когда люди перебивают друг друга.
- **Удобно для нейронок.** Подряд идущие фразы одного человека склеиваются в реплику, длинный монолог делится на абзацы примерно раз в 45 секунд.
- **Любой формат, который читает ffmpeg**: m4a, mp3, wav, ogg, flac, mp4, mov, webm…
- **Использует видеокарту**, где может: NVIDIA (CUDA) для всего, GPU Apple Silicon для разделения по спикерам.
- **Понятный прогресс**: этапы с полосами и оценкой оставшегося времени; битый файл не останавливает пачку.

## Требования

| | |
|---|---|
| ОС | macOS на Apple Silicon, Linux, Windows. Mac на Intel не поддерживается (под него нет сборок PyTorch). |
| Инструменты | [uv](https://docs.astral.sh/uv/getting-started/installation/) и [ffmpeg](https://ffmpeg.org/download.html). Нужный Python uv поставит сам. |
| Диск | ~2 ГБ на Python-пакеты (~6 ГБ на Linux, там PyTorch идёт с CUDA) + 2–4 ГБ на модели |
| Память | минимум 8 ГБ, лучше 16 ГБ |
| Разделение по спикерам | бесплатный аккаунт и токен [Hugging Face](https://huggingface.co) (см. ниже) |

Установка инструментов:

```bash
# macOS
brew install uv ffmpeg

# Debian / Ubuntu
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt install ffmpeg

# Windows
winget install astral-sh.uv
winget install Gyan.FFmpeg
```

## Установка

Как глобальная команда (рекомендуется):

```bash
uv tool install git+https://github.com/Vovamujik/meeting-transcriber
```

Или из клона, если хочешь менять код:

```bash
git clone https://github.com/Vovamujik/meeting-transcriber
cd meeting-transcriber
uv sync
uv run meeting-transcriber --help
```

## Токен Hugging Face (для разделения по спикерам)

Модель [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) бесплатная, но закрыта соглашением: один раз нужно принять условия, в том числе согласиться передать свои контакты команде pyannote.

1. Прими условия на [странице модели](https://huggingface.co/pyannote/speaker-diarization-community-1).
2. Создай токен с типом **Read**: <https://huggingface.co/settings/tokens>.
3. Передай его тулзе любым способом:
   - `uvx --from huggingface_hub hf auth login` (токен сохранится для всех инструментов Hugging Face);
   - положи `HF_TOKEN=hf_...` в `~/.config/meeting-transcriber/.env` (шаблон: [.env.example](.env.example));
   - при запуске из клона: файл `.env` в корне репозитория;
   - `export HF_TOKEN=hf_...` в терминале.

Спикеры не нужны? Пропусти этот шаг и запускай с `--no-diarize`.

Проверить всё разом:

```bash
meeting-transcriber --check
```

```
meeting-transcriber 0.1.0 · Python 3.12.6 · Darwin arm64
  ✓ ffmpeg: /opt/homebrew/bin/ffmpeg
  ✓ Whisper on cpu (int8), speaker diarization on mps
  ✓ Hugging Face token found, access to pyannote/speaker-diarization-community-1 confirmed
```

## Запуск

```bash
meeting-transcriber ~/Downloads/meeting.m4a --lang ru
```

`.txt` появится рядом с записью, а путь к нему печатается в stdout. Первый запуск скачает модели (2–4 ГБ) в `~/.cache/huggingface`, дальше всё работает без интернета.

```bash
# несколько файлов в одну папку
meeting-transcriber ~/Recordings/*.m4a --lang ru -o transcripts

# известно, сколько людей на встрече: спикеры определятся точнее
meeting-transcriber call.mp4 --lang ru --speakers 4

# максимальная точность (в 2–3 раза медленнее)
meeting-transcriber call.mp4 --lang ru --model large-v3

# без токена Hugging Face: текст без разделения по спикерам
meeting-transcriber call.mp4 --no-diarize
```

Во время работы видно каждый этап: прогресс, прошедшее время и сколько примерно осталось.

```
Loading models
  ✓ speaker diarization (pyannote, mps) · 1.9s
  ✓ whisper large-v3-turbo (cpu, int8) · 2.3s
  ✓ alignment (ru) · 3.7s

[1/2] planning.m4a
  42:13 · language ru
  ✓ Transcribe    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%  9:12
  ⠴ Align words   ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━  62%  1:05  ~0:40 left
  · Speakers      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Опции

| Опция | Что делает |
|---|---|
| `-l, --lang КОД` | Язык записи (`ru`, `en`, `de`, …). Без неё язык определяется по первым 30 секундам. |
| `-m, --model ИМЯ` | `large-v3-turbo` (по умолчанию, быстро), `large-v3` (точнее всего), `medium`, `small` |
| `-o, --out ПАПКА` | Куда сохранять `.txt` (по умолчанию рядом с каждой записью) |
| `-s, --speakers N` | Точное число спикеров, если известно |
| `--min-speakers N`, `--max-speakers N` | Диапазон, если точное число неизвестно |
| `--no-diarize` | Без разделения по спикерам (токен не нужен) |
| `--device auto\|cuda\|cpu` | Где распознавать речь. `auto` берёт видеокарту NVIDIA, если она есть. |
| `--diarize-device auto\|cuda\|mps\|cpu` | Где считать спикеров. `auto`: NVIDIA, затем GPU Apple, затем CPU. |
| `--compute-type ТИП` | Точность Whisper: по умолчанию `float16` на GPU и `int8` на CPU |
| `--batch-size N` | По умолчанию 8. Уменьши, если не хватает памяти. |
| `--check` | Проверить ffmpeg, токен и устройства и выйти |
| `-v, --verbose` | Показывать логи и предупреждения библиотек |

Коды выхода: `0` все файлы готовы, `1` хотя бы один упал (остальные всё равно обрабатываются), `130` прервано.

### Формат расшифровки

- Короткая шапка (файл, длительность, язык, число спикеров), дальше по абзацу на реплику: `[ЧЧ:ММ:СС] Спикер N: текст`.
- Спикеры нумеруются по первому появлению. Имён тулза не знает, поэтому подскажи нейронке, кто есть кто: «Спикер 1 — это Аня, она ведёт встречу».
- Подписи зависят от языка записи: для русского `Спикер 1`, `Файл:` и так далее, для всех остальных языков английские.

Сообщения в терминале на английском, как принято в open source.

## Использование с агентами

В репозитории есть [Agent Skill](https://agentskills.io): [`skills/transcribe-meeting`](skills/transcribe-meeting/SKILL.md). Он объясняет агенту, как проверить окружение, запустить расшифровку в фоне и потом работать с текстом: саммари, протокол, задачи. uv, ffmpeg и токен Hugging Face для спикеров всё равно нужны.

**Claude Code** (как плагин):

```
/plugin marketplace add Vovamujik/meeting-transcriber
/plugin install meeting-transcriber@vovamujik
```

**Любой агент** (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode, …) через [`skills`](https://github.com/vercel-labs/skills):

```bash
npx skills add Vovamujik/meeting-transcriber -g
```

Или скопируй `skills/transcribe-meeting` в папку скилов своего агента (для Claude Code это `~/.claude/skills/`).

Дальше просто попроси: *«Расшифруй ~/Downloads/standup.m4a и выпиши задачи с ответственными».*

Скил работает только с агентами, которые запущены на твоём компьютере. В claude.ai и других облачных песочницах модели не скачать, и там нет видеокарты.

## Скорость

Замер на Apple M3 Pro (18 ГБ), модель `large-v3-turbo`, запись на 3 минуты с двумя голосами: около минуты на всё (в 3 раза быстрее реального времени). Распознавание 35 с на CPU, выравнивание 9 с, спикеры 10 с на GPU Apple (на CPU было бы 97 с). Часовая встреча занимает примерно 20 минут. На видеокартах NVIDIA сильно быстрее.

## Частые проблемы

| Проблема | Что делать |
|---|---|
| `GatedRepoError`, `401`, `403` | Не приняты условия модели или нет токена. См. [Токен Hugging Face](#токен-hugging-face-для-разделения-по-спикерам) и запусти `--check`. |
| `ffmpeg not found` | Поставь ffmpeg (см. [Требования](#требования)). |
| `CERTIFICATE_VERIFY_FAILED` | На macOS исправляется автоматически. За корпоративным прокси укажи в `SSL_CERT_FILE` и `REQUESTS_CA_BUNDLE` сертификаты компании. |
| Скачивание зависло или медленное | Загрузка продолжается с места остановки: прерви по Ctrl+C и запусти снова. |
| Не хватает памяти | `--model medium` или `--batch-size 4` |
| Ошибки CUDA / cuDNN на Linux | См. [заметки WhisperX про cuDNN](https://github.com/m-bain/whisperX/blob/main/CUDNN_TROUBLESHOOTING.md) или запускай с `--device cpu --diarize-device cpu`. |
| Фразы-призраки вроде «Thank you.» или «Продолжение следует…» | На длинной тишине Whisper иногда «слышит» дежурные фразы. Это особенность модели. |

## Ограничения

- На macOS распознавание речи идёт на CPU: faster-whisper (CTranslate2) не поддерживает GPU Apple. Спикеры считаются на GPU.
- Когда люди говорят одновременно, текст достаётся одному из них.
- Один человек иногда делится на двух спикеров (например, после смены микрофона), а похожие голоса иногда сливаются в один. Помогает `--speakers N`.
- Выравнивание по словам есть для [этих языков](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py). Для остальных спикеры назначаются целым фразам, а не словам.

## Модели и лицензии

Код проекта под лицензией MIT. Модели скачиваются у авторов при первом запуске и распространяются на своих условиях:

| Модель | Для чего | Лицензия |
|---|---|---|
| [faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) (OpenAI Whisper) | распознавание речи | MIT |
| [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | разделение по спикерам | CC BY 4.0, по соглашению |
| [wav2vec2-large-xlsr-53-russian](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-russian) | выравнивание для русского | Apache 2.0 |
| [WAV2VEC2_ASR_BASE_960H](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html) | выравнивание для английского | MIT |
| [VOXPOPULI_ASR_BASE_10K_*](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.VOXPOPULI_ASR_BASE_10K_FR.html) | выравнивание для французского, немецкого, испанского, итальянского | **CC BY-NC 4.0 (только некоммерческое использование)** |

Модели выравнивания для других языков перечислены в WhisperX; перед коммерческим использованием проверь лицензию каждой. Whisper может ошибаться и «галлюцинировать», поэтому в ответственных задачах не полагайся только на него.

## Разработка

```bash
uv sync                      # вместе с pytest и ruff
uv run pytest                # тесты чистой логики, модели не нужны
uv run ruff check src tests
claude plugin validate .     # манифесты плагина и скила
```

Кода немного: `src/meeting_transcriber/cli.py` (конвейер, CLI, формат расшифровки) и `ui.py` (вывод в терминал). Issues и pull requests приветствуются; в баг-репорте укажи ОС, видеокарту, команду и вывод с `--verbose`.

## Благодарности

[WhisperX](https://github.com/m-bain/whisperX) (Max Bain и соавторы), [pyannote.audio](https://github.com/pyannote/pyannote-audio) (Hervé Bredin и соавторы), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) от SYSTRAN и [Whisper](https://github.com/openai/whisper) от OpenAI. Если используешь результаты разделения по спикерам в исследованиях, процитируй pyannote, как просят на странице модели.

## Лицензия

[MIT](LICENSE)
