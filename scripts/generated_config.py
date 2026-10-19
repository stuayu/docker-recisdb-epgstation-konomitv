"""Track complete generated files; preserve any subsequent user changes."""
import hashlib
import json
from pathlib import Path

from editable import backup


def digest(content):
    return hashlib.sha256(content).hexdigest()


def state_path(root):
    return Path(root) / 'config/.generated-configs.json'


def load(root):
    path = state_path(root)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()) else {}
    except (ValueError, OSError):
        # Corrupt provenance must never authorize overwriting a file.
        return {}


def remember(root, path):
    state = load(root)
    state[str(path.relative_to(root))] = digest(path.read_bytes())
    destination = state_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(state, indent=2) + '\n')
    destination.chmod(0o600)


def replace_generated(root, path, text, baseline=None):
    """Replace only tracked output or a byte-for-byte unchanged old template."""
    if path.is_symlink() or not path.is_file():
        return False
    old = path.read_bytes()
    state = load(root)
    expected = state.get(str(path.relative_to(root)))
    # Once tracked, even restoring the old software template is a manual edit.
    # Untracked legacy files can be adopted; corrupt/empty provenance cannot
    # authorize adoption. Other services may already have populated the file.
    managed = digest(old) == expected if expected is not None else (
        (bool(state) or not state_path(root).exists())
        and baseline is not None and old == baseline.encode())
    if not managed:
        print(f'手動設定を維持: {path.relative_to(root)}')
        return False
    new = text.encode()
    if old == new:
        remember(root, path)
        return False
    saved = backup(path)
    # Keep the inode used by running file bind mounts.
    path.write_bytes(new)
    remember(root, path)
    print(f'GPU 設定を反映: {path.relative_to(root)}; 退避: {saved.name}')
    return True
