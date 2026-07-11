"""Check OPENAI_API_KEY load state without printing secrets."""

from __future__ import annotations

from src.env import load_env, openai_api_key_status, project_root


def main() -> None:
    env_path = project_root() / ".env"
    print("env_path:", env_path)
    print("env_exists:", env_path.is_file())

    states = []
    if env_path.is_file():
        for i, raw in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
            s = raw.strip()
            if "OPENAI_API_KEY" not in s:
                continue
            if s.startswith("#") and "OPENAI_API_KEY=" in s:
                states.append((i, "commented_out"))
            elif s.startswith("OPENAI_API_KEY="):
                val = s.split("=", 1)[1].strip().strip('"').strip("'")
                states.append((i, "active_nonempty" if val else "active_empty"))
            else:
                states.append((i, "other_form"))

    print("openai_lines:", states if states else "none")

    load_env(override=True)
    status = openai_api_key_status()
    print("detected:", status["present"])
    print("length:", status["length"])
    print("prefix:", status["prefix"])
    print("model:", status["model"])


if __name__ == "__main__":
    main()
