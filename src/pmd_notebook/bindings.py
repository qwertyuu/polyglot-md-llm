from __future__ import annotations

import shlex
import sys

from .models import Cell, Document


PYTHON_BINDING = r'''import json as _pmd_json, os as _pmd_os, shutil as _pmd_shutil
from pathlib import Path as _PmdPath
class _PmdContext:
    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        return self.get(key)
    def __setattr__(self, key, value):
        if key.startswith("_"):
            object.__setattr__(self, key, value)
        else:
            self.set(key, value)
    def __getitem__(self, key):
        return self.get(key)
    def __setitem__(self, key, value):
        self.set(key, value)
    def _read(self):
        with open(_pmd_os.environ["PMD_CTX_FILE"], encoding="utf-8") as stream:
            return _pmd_json.load(stream)
    def get(self, key, *default):
        data = self._read()
        if key in data:
            return data[key]
        if default:
            return default[0]
        raise KeyError(f"PMD ctx key not set: {key}")
    def has(self, key):
        return key in self._read()
    def set(self, key, value):
        if not isinstance(key, str):
            raise TypeError("PMD ctx keys must be strings")
        _pmd_json.dumps(value)
        data = self._read()
        data[key] = value
        with open(_pmd_os.environ["PMD_CTX_FILE"], "w", encoding="utf-8") as stream:
            _pmd_json.dump(data, stream, ensure_ascii=False, sort_keys=True)
ctx = _PmdContext()
class _PmdDisplay:
    def _path(self, name, suffix):
        name = name or f"output.{suffix}"
        if not name.lower().endswith(f".{suffix}"):
            name += f".{suffix}"
        return _PmdPath(_pmd_os.environ["PMD_CELL_OUT"]) / name
    def markdown(self, text, name="output.md"):
        self._path(name, "md").write_text(str(text), encoding="utf-8")
    def csv(self, text, name="output.csv"):
        self._path(name, "csv").write_text(str(text), encoding="utf-8")
    def image(self, path, name=None):
        source = _PmdPath(path)
        _pmd_shutil.copy2(source, _PmdPath(_pmd_os.environ["PMD_CELL_OUT"]) / (name or source.name))
    def file(self, path, name=None):
        self.image(path, name)
display = _PmdDisplay()
class _PmdOutputs:
    def _roots(self):
        return _pmd_json.loads(_pmd_os.environ.get("PMD_DEP_OUTPUTS", "{}"))
    def path(self, cell_id, name):
        roots = self._roots()
        if cell_id not in roots:
            raise KeyError(f"PMD dependency outputs unavailable for cell: {cell_id}")
        root = _PmdPath(roots[cell_id]).resolve()
        candidate = (root / name).resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError("PMD output path must stay inside the dependency output directory")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate
    def files(self, cell_id):
        roots = self._roots()
        if cell_id not in roots:
            raise KeyError(f"PMD dependency outputs unavailable for cell: {cell_id}")
        root = _PmdPath(roots[cell_id])
        return sorted(path for path in root.rglob("*") if path.is_file())
outputs = _PmdOutputs()
'''


def _shell_binding() -> str:
    python = shlex.quote(sys.executable)
    get_code = "import json,os,sys;d=json.load(open(os.environ['PMD_CTX_FILE'],encoding='utf-8'));k=sys.argv[1];k in d or (_ for _ in ()).throw(KeyError('PMD ctx key not set: '+k));print(json.dumps(d[k],ensure_ascii=False))"
    set_code = "import json,os,sys;p=os.environ['PMD_CTX_FILE'];d=json.load(open(p,encoding='utf-8'));d[sys.argv[1]]=json.loads(sys.argv[2]);json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,sort_keys=True)"
    has_code = "import json,os,sys;d=json.load(open(os.environ['PMD_CTX_FILE'],encoding='utf-8'));raise SystemExit(0 if sys.argv[1] in d else 1)"
    return (
        f"ctx_get() {{ {python} -c {shlex.quote(get_code)} \"$1\"; }}\n"
        f"ctx_set() {{ {python} -c {shlex.quote(set_code)} \"$1\" \"$2\"; }}\n"
        f"ctx_has() {{ {python} -c {shlex.quote(has_code)} \"$1\"; }}\n"
    )


POWERSHELL_BINDING = r'''function Get-CtxValue([string]$Key) {
  $data = Get-Content -Raw -LiteralPath $env:PMD_CTX_FILE | ConvertFrom-Json
  $property = $data.PSObject.Properties[$Key]
  if ($null -eq $property) { throw "PMD ctx key not set: $Key" }
  return $property.Value
}
function Test-CtxValue([string]$Key) {
  $data = Get-Content -Raw -LiteralPath $env:PMD_CTX_FILE | ConvertFrom-Json
  return $null -ne $data.PSObject.Properties[$Key]
}
function Set-CtxValue([string]$Key, $Value) {
  $data = Get-Content -Raw -LiteralPath $env:PMD_CTX_FILE | ConvertFrom-Json
  $property = $data.PSObject.Properties[$Key]
  if ($null -eq $property) { $data | Add-Member -NotePropertyName $Key -NotePropertyValue $Value }
  else { $property.Value = $Value }
  $data | ConvertTo-Json -Depth 100 -Compress | Set-Content -LiteralPath $env:PMD_CTX_FILE -Encoding utf8
}
'''


def _binding_preamble(language: str) -> str:
    if language in {"python", "python3"}:
        return PYTHON_BINDING
    if language in {"bash", "sh"}:
        return _shell_binding()
    if language in {"pwsh", "powershell"}:
        return POWERSHELL_BINDING
    return ""


def resolve_uses(cell: Cell, document: Document) -> list[Cell]:
    lookup = document.lookup
    return [lookup[name] for name in cell.uses if name in lookup and lookup[name].role == "lib"]


def source_with_binding(cell: Cell, document: Document | None = None) -> str:
    preamble = _binding_preamble(cell.language)
    lib_source = "".join(lib.source + "\n" for lib in resolve_uses(cell, document)) if document is not None else ""
    if not preamble and not lib_source:
        return cell.source
    return preamble + ("\n" if preamble else "") + lib_source + cell.source
