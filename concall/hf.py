"""Hugging Face connection for speaker separation.

The pyannote models are free but "gated": you need an account, must click
"Agree" on two model pages, and give the app a read token. This module checks
each of those so the Settings screen can tell you exactly which step is missing.
"""

from . import components, config

TOKEN_PAGE = "https://huggingface.co/settings/tokens"
JOIN_PAGE = "https://huggingface.co/join"


def model_page(repo: str) -> str:
    return f"https://huggingface.co/{repo}"


def check(token: str) -> dict:
    """Verify the token and access to each gated model. Never raises."""
    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.utils import EntryNotFoundError, GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

    token = (token or "").strip()
    result = {"ok": False, "username": None, "token_valid": False, "missing_terms": [], "error": None}
    if not token:
        result["error"] = "Paste your token first."
        return result
    if not token.startswith("hf_"):
        result["error"] = "That doesn't look like a Hugging Face token (they start with hf_)."
        return result
    try:
        who = HfApi().whoami(token=token)
        result["username"] = who.get("name")
        result["token_valid"] = True
    except HfHubHTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        result["error"] = "Hugging Face rejected this token. Create a new one (type: Read) and paste it again." if status in (401, 403) else f"Couldn't reach Hugging Face: {exc}"
        return result
    except Exception as exc:
        result["error"] = f"Couldn't reach Hugging Face. Check your internet connection. ({exc})"
        return result

    for repo in config.DIARIZATION_GATED:
        try:
            hf_hub_download(repo, "config.yaml", token=token)
        except GatedRepoError:
            result["missing_terms"].append({"repo": repo, "url": model_page(repo)})
        except (EntryNotFoundError, RepositoryNotFoundError):
            pass  # access works; file layout changed
        except Exception as exc:
            result["error"] = f"Couldn't check {repo}: {exc}"
            return result
    result["ok"] = not result["missing_terms"]
    return result


def connect(token: str) -> dict:
    result = check(token)
    if result["token_valid"]:
        config.save_settings({"hf_token": token.strip(), "diarization": True,
                              "hf_ok": result["ok"], "hf_user": result["username"] or ""})
    if result["ok"]:
        start_setup()
    return result


def recheck() -> dict:
    result = check(config.hf_token())
    if result["token_valid"]:
        config.save_settings({"hf_ok": result["ok"], "hf_user": result["username"] or ""})
    if result["ok"]:
        start_setup()
    return result


def start_setup() -> None:
    """Install pyannote, then download its weights, in the background."""
    import threading

    def run():
        try:
            if not components.package_installed("speakers"):
                components.wait(components.install("speakers"))
            components.wait(components.download_speaker_model())
        except Exception:
            import traceback

            traceback.print_exc()

    threading.Thread(target=run, daemon=True, name="hf-setup").start()


def disconnect() -> None:
    config.save_settings({"hf_token": "", "hf_ok": False, "hf_user": ""})


def status() -> dict:
    token = config.hf_token()
    settings = config.load_settings()
    return {
        "connected": bool(token),
        "ready": config.hf_ready(),
        "username": settings["hf_user"],
        "token_hint": (token[:5] + "…" + token[-4:]) if token else "",
        "enabled": config.diarization_enabled(),
        "join_url": JOIN_PAGE,
        "token_url": TOKEN_PAGE,
        "models": [{"repo": r, "url": model_page(r)} for r in config.DIARIZATION_GATED],
    }
