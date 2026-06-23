# Switchboard — how to use it (the whole thing)

## 1. Start Claude Code on an open (OpenRouter) model
In a terminal:
```
ccr code
```
This launches Claude Code running on an OpenRouter model instead of Anthropic.

## 2. Switch models WHILE inside a session
Type this in the session (copy the MODEL from `sb list`):
```
/model openrouter,deepseek/deepseek-v4-flash
```
For web search, append `:online`:
```
/model openrouter,deepseek/deepseek-v4-flash:online
```

## 3. See or change models (in a normal terminal, NOT inside Claude)
```
sb list                              # show all companies (providers) + model counts
sb list deepseek                     # drill into one company's models (+ switch hints)
sb list qwen                         # ...or search by any keyword
sb use deepseek/deepseek-v4-flash    # set this model as default + restart CCR
sb current                           # show the current model
```
(If `sb` is not found, open a NEW terminal so the profile reloads, or use the full form:
`uv run --project "%USERPROFILE%\Dev\switchboard" python "%USERPROFILE%\Dev\switchboard\switchboard.py" list`.)
Note: switchboard is a uv project (`.venv` lives in the repo); `sb` runs it via `uv run`.

## 4. Go back to normal Claude (Anthropic)
Just run:
```
claude
```
Plain `claude` = Anthropic, untouched. `ccr code` = OpenRouter. Two separate worlds.

## Known limitation
- **Web search / reading web pages is unreliable on open models.** For web research,
  use normal `claude`. (Web search is an Anthropic-native feature and does not fully
  work through OpenRouter; appending `:online` to a model gives web-augmented answers
  but bills extra.)
