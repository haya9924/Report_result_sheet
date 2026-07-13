"""resultsheet の例外階層。

すべてのエラーメッセージは GUI / CLI にそのまま表示されるため日本語で書く。
"""


class ResultSheetError(Exception):
    """resultsheet のすべてのエラーの基底クラス。"""


class DefinitionError(ResultSheetError):
    """定義YAMLの構文・スキーマ・参照エラー。"""


class CycleError(DefinitionError):
    """計算式の循環依存。"""


class EvalError(ResultSheetError):
    """計算式の評価エラー(禁止構文・未定義変数・数値エラーなど)。"""


class StoreError(ResultSheetError):
    """results.json / definition.yaml の読み書きエラー。"""
