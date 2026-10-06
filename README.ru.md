# meeting-transcriber

[English](README.md) · **Русский**

Локальная расшифровка встреч с разделением по спикерам и [Agent Skill](https://agentskills.io) для Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI и OpenCode.

Дай агенту запись или видео созвона и попроси саммари, протокол или список задач. Он расшифрует всё **на твоём компьютере** с помощью [WhisperX](https://github.com/m-bain/whisperX) и [pyannote](https://github.com/pyannote/pyannote-audio) и будет работать с такой расшифровкой:

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

## Подключить скил к агенту

Четыре шага. Агент должен работать на твоём компьютере (Claude Code, Codex, Cursor, …): в claude.ai и других облачных песочницах модели не скачать.

### 1. Поставь uv, ffmpeg и git

```bash
# macOS
brew install uv ffmpeg

# Debian / Ubuntu
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt install ffmpeg git

# Windows
winget install astral-sh.uv
winget install Gyan.FFmpeg
winget install Git.Git
```

| Что нужно | |
|---|---|
| ОС | macOS 14+ на Apple Silicon, Linux или Windows. Mac на Intel не поддерживается (под него нет сборок PyTorch). |
| Инструменты | [uv](https://docs.astral.sh/uv/getting-started/installation/) (нужный Python поставит сам), [ffmpeg](https://ffmpeg.org/download.html) вместе с ffprobe (он есть в любой стандартной сборке), [git](https://git-scm.com/downloads) |
| Диск | ~2 ГБ на Python-пакеты (~7,5 ГБ на Linux x86_64, там PyTorch идёт с CUDA) + 2–4 ГБ на модели |
| Память | минимум 8 ГБ, лучше 16 ГБ |

### 2. Получи токен Hugging Face (для разделения по спикерам)

Кто что сказал, определяет модель [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1). Она бесплатная, но закрыта соглашением: один раз нужно принять условия, в том числе согласиться передать свои контакты команде pyannote.

1. Заведи бесплатный аккаунт на [Hugging Face](https://huggingface.co) и прими условия на [странице модели](https://huggingface.co/pyannote/speaker-diarization-community-1).
2. Создай токен с типом **Read**: <https://huggingface.co/settings/tokens>.
3. Сохрани его в терминале:
   ```bash
   uvx --from huggingface_hub hf auth login
   ```
   Выбери **Paste an access token** и вставь токен. (Токены от входа через браузер истекают, а эта тулза не умеет их обновлять.)

Другие способы передать токен: `HF_TOKEN=hf_...` в `~/.config/meeting-transcriber/.env` (шаблон: [.env.example](.env.example)) или `export HF_TOKEN=hf_...`. Никогда не вставляй токен в чат с агентом.

Нет токена? Пропусти шаг: агент расшифрует запись без разделения по спикерам.

### 3. Подключи скил

**Claude Code** (как плагин), внутри сессии:

```
/plugin marketplace add Vovamujik/meeting-transcriber
/plugin install meeting-transcriber@vovamujik
```

**Любой агент** (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode, …) через [`skills`](https://github.com/vercel-labs/skills):

```bash
npx skills add Vovamujik/meeting-transcriber -g
```

Или скопируй [`skills/transcribe-meeting`](skills/transcribe-meeting/SKILL.md) в папку скилов своего агента (для Claude Code это `~/.claude/skills/`). После этого перезапусти агента.

### 4. Попроси агента

> Расшифруй ~/Downloads/планёрка.m4a и сделай протокол.

> Вот вчерашний созвон: ~/Movies/call.mov. Нас было четверо. Выпиши решения и задачи с ответственными.

> Transcribe ~/Downloads/standup.m4a and list the action items with owners.

Что произойдёт:

1. Агент проверит окружение (ffmpeg, токен, устройства) и скажет, если чего-то не хватает.
2. **Первый запуск долгий**: ставятся Python-пакеты и скачиваются модели (10+ минут). Дальше всё стартует за секунды и работает без интернета.
3. Расшифровка идёт в фоне, примерно треть длины записи на Mac с Apple Silicon (час ≈ 20 минут), на видеокартах NVIDIA сильно быстрее.
4. Расшифровка сохранится рядом с записью (`call.txt`), и агент ответит на твой запрос по ней.

Советы: скажи язык и сколько было людей, подскажи, кто есть кто («Спикер 1 — это Аня»). Видео подходит как есть, конвертировать заранее не нужно.

Хочешь проверить окружение сам, до того как просить агента?

```bash
uvx --from git+https://github.com/Vovamujik/meeting-transcriber meeting-transcriber --check
```

```
meeting-transcriber 0.2.0 · Python 3.12.6 · Darwin arm64
  ✓ ffmpeg: /opt/homebrew/bin/ffmpeg
  ✓ Whisper on cpu (int8), speaker diarization on mps
  ✓ Hugging Face token from `hf auth login` (account you), access to pyannote/speaker-diarization-community-1 confirmed
```

## Что умеет

- **Приватно.** Аудио не покидает компьютер. Из сети при первом запуске скачиваются только веса моделей; телеметрия pyannote отключена.
- **Аудио или видео.** m4a, mp3, wav, ogg, flac, mp4, mov, mkv, webm — всё, что читает ffmpeg. Из видео звук достаётся автоматически, а если звуковых дорожек несколько (например, OBS, где микрофон и звук системы пишутся на разные дорожки), они смешиваются, чтобы никто не потерялся.
- **Спикеры привязаны к словам.** Каждое слово выравнивается по времени и получает своего спикера, поэтому реплики режутся правильно, даже когда люди перебивают друг друга.
- **Удобно для нейронок.** Подряд идущие фразы одного человека склеиваются в реплику, длинный монолог делится на абзацы примерно раз в 45 секунд.
- **Использует видеокарту**, где может: NVIDIA (CUDA) на Linux для всего, GPU Apple Silicon для разделения по спикерам. На Windows всё идёт на CPU (PyTorch с PyPI там без CUDA).

Про формат расшифровки:

- Короткая шапка (файл, длительность, язык, число спикеров), дальше по абзацу на реплику: `[ЧЧ:ММ:СС] Спикер N: текст`.
- Спикеры нумеруются по первому появлению. Имён тулза не знает, поэтому подскажи нейронке, кто есть кто.
- Подписи зависят от языка записи: для русского `Спикер 1`, `Файл:` и так далее, для всех остальных языков английские. Сообщения в терминале на английском, как принято в open source.

## Командная строка (без агента)

Шаги 1 и 2 выше нужны и здесь. Потом поставь команду:

```bash
uv tool install git+https://github.com/Vovamujik/meeting-transcriber
```

Или из клона, если хочешь менять код (тогда запускай команды ниже через `uv run`):

```bash
git clone https://github.com/Vovamujik/meeting-transcriber
cd meeting-transcriber
uv sync
uv run meeting-transcriber --help
```

Запуск:

```bash
meeting-transcriber ~/Downloads/meeting.m4a --lang ru
```

`.txt` появится рядом с записью, а путь к нему печатается в stdout. Существующий файл не перезаписывается: повторный запуск создаст `meeting (2).txt`. Первый запуск скачает модели (2–4 ГБ) в `~/.cache/huggingface`, дальше всё работает без интернета (если Hugging Face недоступен, сразу берутся модели из кэша).

```bash
# несколько файлов в одну папку
meeting-transcriber ~/Recordings/*.m4a --lang ru -o transcripts

# известно, сколько людей на встрече: спикеры определятся точнее
meeting-transcriber call.mp4 --lang ru --speakers 4

# видео подходит как есть: звук достаётся автоматически
meeting-transcriber ~/Movies/zoom-call.mov --lang ru

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

[1/2] planning.mp4
  ✓ Extract audio ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%  0:14
  42:13 · language ru · video, 2 audio tracks mixed
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
| `--device auto\|cuda\|cpu` | Где распознавать речь. `auto` берёт видеокарту NVIDIA, если она есть (Linux; на Windows PyTorch по умолчанию без CUDA). |
| `--diarize-device auto\|cuda\|mps\|cpu` | Где считать спикеров. `auto`: NVIDIA, затем GPU Apple, затем CPU. |
| `--compute-type ТИП` | Точность Whisper: по умолчанию `float16` на GPU и `int8` на CPU |
| `--batch-size N` | По умолчанию 8. Уменьши, если не хватает памяти. |
| `--check` | Проверить ffmpeg, токен и устройства и выйти |
| `-v, --verbose` | Показывать логи и предупреждения библиотек |

Коды выхода: `0` все файлы готовы, `1` хотя бы один упал (остальные всё равно обрабатываются), `130` прервано.

## Скорость

Замер на Apple M3 Pro (18 ГБ), модель `large-v3-turbo`, запись на 3 минуты с двумя голосами: около минуты на всё (в 3 раза быстрее реального времени). Распознавание 35 с на CPU, выравнивание 9 с, спикеры 10 с на GPU Apple (на CPU было бы 97 с). Часовая встреча занимает примерно 20 минут. На видеокартах NVIDIA сильно быстрее.

## Частые проблемы

| Проблема | Что делать |
|---|---|
| `GatedRepoError`, `401`, `403` | Запусти `--check`: он покажет, откуда взят токен и что с ним не так (нет токена, токен недействителен, условия не приняты на этом аккаунте, fine-grained токен без доступа к gated-репозиториям). См. [шаг 2](#2-получи-токен-hugging-face-для-разделения-по-спикерам). |
| Токен «invalid or expired (HTTP 401)» сразу после `hf auth login` | Старый `HF_TOKEN`, экспортированный в профиле терминала (`~/.zshrc`, `~/.bashrc`; на Windows — переменная окружения пользователя) или записанный в `.env`, главнее токена от `hf auth login`. Удали его, открой новый терминал и перезапусти агента; `--check` покажет, откуда он берётся. |
| Долго висит «Starting…» | Первый запуск после установки или обновления компилирует Python-пакеты: до нескольких минут, один раз. |
| `ffmpeg not found` | Поставь ffmpeg (см. [шаг 1](#1-поставь-uv-ffmpeg-и-git)). |
| `CERTIFICATE_VERIFY_FAILED` | На macOS исправляется автоматически. За корпоративным прокси укажи в `SSL_CERT_FILE` и `REQUESTS_CA_BUNDLE` сертификаты компании. |
| Скачивание зависло или медленное | Загрузка продолжается с места остановки: прерви по Ctrl+C и запусти снова. |
| Не хватает памяти | `--model medium` или `--batch-size 4` |
| Ошибки CUDA / cuDNN на Linux | См. [заметки WhisperX про cuDNN](https://github.com/m-bain/whisperX/blob/main/CUDNN_TROUBLESHOOTING.md) или запускай с `--device cpu --diarize-device cpu`. |
| `no audio track in the video` | В записи вообще нет звука (например, запись экрана без звука). |
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
uv run pytest                # модели не нужны
uv run ruff check src tests
claude plugin validate .     # манифесты маркетплейса и плагина
uvx --from skills-ref agentskills validate skills/transcribe-meeting
```

Выпуск версии: подними версию в `pyproject.toml` и `.claude-plugin/plugin.json`, поставь тег `vX.Y.Z`, запушь его, затем закрепи `RELEASE` в `skills/transcribe-meeting/scripts/run.sh` и строку `uvx` в `SKILL.md` на новый релиз.

Кода немного: `src/meeting_transcriber/cli.py` (конвейер, CLI, формат расшифровки), `media.py` (извлечение звука) и `ui.py` (вывод в терминал). Issues и pull requests приветствуются; в баг-репорте укажи ОС, видеокарту, команду и вывод с `--verbose`.

## Благодарности

[WhisperX](https://github.com/m-bain/whisperX) (Max Bain и соавторы), [pyannote.audio](https://github.com/pyannote/pyannote-audio) (Hervé Bredin и соавторы), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) от SYSTRAN и [Whisper](https://github.com/openai/whisper) от OpenAI. Если используешь результаты разделения по спикерам в исследованиях, процитируй pyannote, как просят на странице модели.

## Лицензия

[MIT](LICENSE)
