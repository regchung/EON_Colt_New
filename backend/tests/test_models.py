"""模型註冊回歸測試:確保每個 model 類別都在 app/models/__init__ 被匯入。

背景:曾因 __init__ 漏匯入數個模型 → 不在 Base.metadata → alembic check 誤判要刪表(漂移)。
本測試掃描所有 model 模組,斷言每個 Base 子類別都能從 app.models 套件命名空間取得
(代表 __init__ 有匯入它),防止該類 bug 再犯。
"""
import importlib
import inspect
import os
import pkgutil

import app.models as models_pkg
from app.db.base import Base


def test_all_models_imported_in_init():
    pkg_dir = os.path.dirname(models_pkg.__file__)
    missing = []
    for _, modname, _ in pkgutil.iter_modules([pkg_dir]):
        mod = importlib.import_module(f"app.models.{modname}")
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            # 只看「定義在此模組」的 Base 子類別(排除 import 進來的)
            if issubclass(obj, Base) and obj is not Base and obj.__module__ == mod.__name__:
                if not hasattr(models_pkg, name):
                    missing.append(f"{modname}.{name}")
    assert not missing, (
        "下列 model 未在 app/models/__init__ 匯入(會造成 alembic 漂移): " + ", ".join(missing)
    )


def test_models_in_metadata():
    """所有已匯入的 model 類別其資料表都應註冊在 Base.metadata。"""
    import app.models  # noqa: F401  觸發 __init__ 匯入
    tables = set(Base.metadata.tables)
    for name in models_pkg.__all__:
        cls = getattr(models_pkg, name)
        tn = getattr(cls, "__tablename__", None)
        if tn is not None:
            assert tn in tables, f"{name}({tn}) 不在 Base.metadata"
