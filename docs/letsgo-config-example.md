# LetsGo configuration example

Create `~/.letsgo.toml` or set `LETSGO_CONFIG` to the path of a TOML file to
customize the LetsGo prompt, theme, and colors. Values may include escape
sequences like `\033` for ANSI colors.

```toml
prompt = ">> "
theme = "dark"
use_color = true
max_log_files = 100

[colors]
green = "\033[32m"
red = "\033[31m"
cyan = "\033[36m"
reset = "\033[0m"
```

Parameters:

- `prompt` – text displayed for the input prompt.
- `theme` – color theme (`light` or `dark`).
- `use_color` – enable or disable colored output.
- `max_log_files` – number of log files to retain.
- `colors.*` – optional ANSI color overrides.
