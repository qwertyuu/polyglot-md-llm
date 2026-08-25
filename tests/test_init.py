from pathlib import Path

from pmd_notebook.cli import _default_project_python, main


def test_default_project_python_is_platform_native() -> None:
    assert _default_project_python("win32") == "{project_dir}/.venv/Scripts/python.exe"
    assert _default_project_python("darwin") == "{project_dir}/.venv/bin/python"
    assert _default_project_python("linux") == "{project_dir}/.venv/bin/python"


def test_init_writes_the_current_platform_interpreter(tmp_path: Path) -> None:
    main(["init", str(tmp_path)])

    config = (tmp_path / "pmd.yaml").read_text(encoding="utf-8")
    assert f'command: "{_default_project_python()}"' in config
    assert (tmp_path / "notebook.pmd").is_file()
