"""Skill scope: what the skill being followed is allowed to run.

Every SKILL.md ends with a boundary — what the step does not do and who owns it
instead — and until now that boundary was prose addressed to a model. A skill
that drifted into the next step's work (afc-query rebuilding an index,
afc-discuss publishing a release, afc-validate repairing what it inspected)
produced a plausible result with no trace of the step it skipped.

`config/skill-scopes.yaml` declares the boundary instead: the scripts each skill
may run and the strongest change it may cause. When AFC_SKILL names the skill
being followed, the `afc` launcher checks the command against it and refuses to
run anything outside, naming the skill that owns it. With AFC_SKILL unset
nothing is enforced, so a direct operator command still works.
"""
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - yaml is a hard requirement at runtime
    yaml = None

from .config import find_afc_home

DEFAULT_CLASSES = ('read-only', 'work', 'release')


class ScopeError(Exception):
    """A command outside the active skill's declared scope."""


class Scopes:
    def __init__(self, data, path=None):
        self.data = data or {}
        self.path = Path(path) if path else None
        self.classes = list(self.data.get('change_classes') or DEFAULT_CLASSES)
        self.scripts = dict(self.data.get('scripts') or {})
        self.skills = dict(self.data.get('skills') or {})

    # --- declarations -----------------------------------------------------
    def skill(self, name):
        return self.skills.get(name)

    def script_class(self, script, subcommand=None):
        """The strongest change this command can cause, or None if undeclared."""
        declared = self.scripts.get(script)
        if declared is None:
            return None
        if isinstance(declared, str):
            return declared
        if subcommand and subcommand in declared:
            return declared[subcommand]
        return declared.get('default')

    def rank(self, change_class):
        try:
            return self.classes.index(change_class)
        except ValueError:
            # An unknown class is treated as the strongest, never the weakest:
            # a typo must not silently widen what a skill may do.
            return len(self.classes)

    def owners(self, script, subcommand=None):
        """Skills whose scope admits this command, for the refusal message."""
        return [name for name in sorted(self.skills)
                if self._violation(name, script, subcommand, resolve_delegates=False) is None]

    # --- enforcement ------------------------------------------------------
    def allowed_scripts(self, name, resolve_delegates=True):
        skill = self.skill(name)
        if skill is None:
            return None
        allowed = set()
        for _, source in self.sources(name, resolve_delegates):
            allowed |= set(source.get('scripts') or [])
        return allowed

    def sources(self, name, resolve_delegates=True):
        """The skill itself, then any skill it delegates to."""
        skill = self.skill(name)
        if skill is None:
            return []
        out = [(name, skill)]
        if resolve_delegates:
            for other in skill.get('delegates') or []:
                nested = self.skill(other)
                if nested:
                    out.append((other, nested))
        return out

    def _violation(self, name, script, subcommand, resolve_delegates=True):
        """The reason this command is out of scope, or None when it is allowed.

        Kept free of the refusal message so that building a message, which asks
        which skills do own the command, cannot recurse back into it.
        """
        skill = self.skill(name)
        if skill is None:
            return 'unknown-skill'
        change = self.script_class(script, subcommand)
        if change is None:
            return 'undeclared-script'

        permitted = set()
        lists_script = False
        for _, source in self.sources(name, resolve_delegates):
            if script not in set(source.get('scripts') or []):
                continue
            lists_script = True
            limit = (source.get('subcommands') or {}).get(script)
            if limit is None:
                permitted = None            # the whole script
                break
            permitted |= set(limit)
        if not lists_script:
            return 'is not in its scope'
        if permitted is not None and subcommand not in permitted:
            return 'is limited to: ' + ', '.join(sorted(permitted))
        ceiling = skill.get('mutation')
        if self.rank(change) > self.rank(ceiling):
            return (f'is a {change} command and {name} may only cause '
                    f'{ceiling} changes')
        return None

    def check(self, name, script, subcommand=None, resolve_delegates=True):
        """Raise ScopeError unless `name` may run this command."""
        if self.skill(name) is None:
            raise ScopeError(
                f'AFC_SKILL names an unknown skill: {name}. '
                f'Known skills: {", ".join(sorted(self.skills)) or "none declared"}.')
        if self.script_class(script, subcommand) is None:
            raise ScopeError(
                f'{script} has no declared change class in '
                f'{self.path or "config/skill-scopes.yaml"}; add one before running it '
                'under a skill.')
        reason = self._violation(name, script, subcommand, resolve_delegates)
        if reason is not None:
            raise ScopeError(self._refusal(name, script, subcommand, reason))
        return True

    def _refusal(self, name, script, subcommand, reason):
        command = f'{script} {subcommand}' if subcommand else script
        lines = [f'{name} may not run {command}: it {reason}.']
        owners = [o for o in self.owners(script, subcommand) if o != name]
        if owners:
            lines.append(f'The skill that owns it: {", ".join(owners)}.')
        handoff = (self.skill(name) or {}).get('handoff') or {}
        if handoff:
            pairs = '; '.join(f'{what} -> {who}' for what, who in handoff.items())
            lines.append(f'{name} hands off: {pairs}.')
        lines.append('Follow that skill instead, or unset AFC_SKILL to run this '
                     'command as a direct operator action.')
        return ' '.join(lines)


_cache = {}


def load_scopes(path=None, home=None, use_cache=True):
    home = Path(home).resolve() if home else find_afc_home()
    cfg = Path(path).resolve() if path else (home / 'config' / 'skill-scopes.yaml')
    if use_cache and str(cfg) in _cache:
        return _cache[str(cfg)]
    data = {}
    if cfg.exists():
        if yaml is None:
            raise RuntimeError('PyYAML is required to read skill-scopes.yaml')
        data = yaml.safe_load(cfg.read_text(encoding='utf-8')) or {}
    scopes = Scopes(data, cfg if cfg.exists() else None)
    if use_cache:
        _cache[str(cfg)] = scopes
    return scopes


def subcommand_of(script, argv, scopes):
    """The first bare word of argv, when this script is keyed by subcommand."""
    declared = scopes.scripts.get(script)
    if not isinstance(declared, dict):
        return None
    for arg in argv:
        if arg == '--':
            continue
        if arg.startswith('-'):
            return None
        return arg
    return None
