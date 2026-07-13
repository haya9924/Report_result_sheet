# resultsheet — 実験レポートの結果入力システム

実験レポートを LaTeX 化するとき、AI(や人間)が **測定値を読み間違えたり、丸めた表示値で再計算して誤差バグを起こす** 問題を構造的に防ぐためのシステムです。

- **計算方式**(変数・単位・計算式・丸め)は `definition.yaml` に定義
- **実験結果**(測定値)は Web GUI から入力し、`results.json` に保存(← 計算方式とは別ファイル)
- 計算はすべて Python 側でフル精度(IEEE754 倍精度)で行い、**丸めは表示のときだけ**。丸めた値が再計算に混ざることは構造的に起こりません
- **すべての操作はブラウザで完結**(スマホ対応)。AI は CLI からフル精度値・表示値・計算式を機械可読で取得できます

## 設計の要点(なぜ誤差バグが減るのか)

1. **計算の一元化**: GUI・CLI・保存値のすべてが同じ Python 計算エンジン(`resultsheet.engine.compute.compute_all`)を通ります。フロントエンドの JavaScript は一切計算しません(入力のたびにサーバへ計算を投げ、結果を表示するだけ)。
2. **フル精度と表示値の分離**: 内部値は常に `float`。表示用の丸め文字列(`display`)は文字列であり、計算の名前空間には決して戻りません → 「丸めた値で再計算」が起こせません。
3. **出力は常に両方を併記**: `resultsheet show` / `get` はフル精度値と丸め済み表示値を同時に出します。AI はレポート執筆時、自分で計算・転記せず **この `display` をそのまま使います**。
4. **検証可能**: `results.json` の真実は入力値のみ。`resultsheet verify` が「保存時の計算」と「現在の定義での再計算」の一致、および定義ファイルのハッシュ一致を検査します。

## セットアップ

```bash
pip install -e .
resultsheet serve            # http://127.0.0.1:8000/ をブラウザで開く
```

以降の操作(レポート作成・計算方式の編集・値入力・保存・散布図・エクスポート)はすべてブラウザ上で行えます。スマホからも同じ URL でアクセスして入力できます。

## 使い方(ブラウザ)

1. **新規レポート**: ホームの「+ 新規レポート」→ ID を入力し、テンプレート選択・YAML 貼り付け・ファイル選択のいずれかで計算方式を指定
2. **計算方式の編集**: 「定義を編集」画面で YAML を編集し「検証」→「保存」。計算式や参照の誤りは保存前に検出されます
3. **結果入力**: 測定値を入力すると導出量が即時に再計算され、丸め値(大)+フル精度値(小)+計算式が表示されます。表は行の追加・削除が可能
4. **散布図**: 任意の 2 列を選んで散布図を表示。フィット直線(最小二乗)を重ねられます
5. **保存**: 「保存」で `results.json` に書き込み
6. **エクスポート**: JSON / Markdown を表示・コピー・ダウンロード

## AI 向け CLI(CUI からのデータ取得)

LaTeX 執筆時、AI は数値を自分で計算・転記せず、必ず以下の出力の `display`(表示値)と `value`(フル精度値)を使ってください。

```bash
resultsheet list                         # レポート一覧
resultsheet show <report> --format json  # 全結果ダンプ(主要参照点)
resultsheet show <report> --format md    # 人間/執筆用の表形式
resultsheet get  <report> <var>          # 1変数の value / display / unit / expr
resultsheet verify <report>              # 保存値と再計算の一致検証(exit 0/1)
resultsheet validate <path.yaml>         # 定義YAMLの静的検証(exit 0/1)
```

`show --format json` の各導出量は次の形です(フル精度値と表示値を必ず併記):

```json
"g_measured": {
  "value": 9.815362392947714,   // フル精度(計算に使う)
  "display": "9.815",           // 表示用の丸め済み(LaTeXにはこれを書く)
  "unit": "m/s^2",
  "expr": "2 * a_slope",
  "rounding": {"sigfigs": 4}
}
```

## 定義 YAML(計算方式)のスキーマ

```yaml
meta:
  id: free_fall            # 英数字・_。レポートの識別子
  title: 自由落下による重力加速度の測定
  description: 任意の説明

constants:                 # 任意。式で使える固定値
  L0: {value: 0.100, unit: m, description: ...}

inputs:                    # スカラー測定値(入力ボックス)
  - name: m                # 式で参照する変数名
    label: 質量            # GUI 表示名
    unit: g                # 任意
    description: ...        # 任意。入力欄の補足
    display: {sigfigs: 3}  # 任意。この入力欄の表示丸め

tables:                    # 繰り返し測定(表)
  - name: drops
    label: 落下測定
    min_rows: 5            # 初期行数(default 3)
    columns:               # 入力列
      - {name: h, label: 落下距離, unit: m}
      - {name: t, label: 落下時間, unit: s}
    derived_columns:       # 行ごとに計算される列(同じ表の列を列名で参照)
      - {name: t2, label: 時間の二乗, expr: "t ** 2", unit: s^2, display: {sigfigs: 4}}

derived:                   # スカラー導出量。table.col で列全体を参照
  - name: a_slope
    label: フィット直線の傾き
    expr: "slope(drops.t2, drops.h)"
    unit: m/s^2
    display: {sigfigs: 4}
  - name: g_measured
    expr: "2 * a_slope"    # 他の導出量も参照可(循環は検出されエラー)
    unit: m/s^2
    display: {sigfigs: 4}
```

### 表示丸め `display`

- `{sigfigs: N}` … 有効数字 N 桁(末尾ゼロ保持、大きすぎ/小さすぎる値は指数表記)
- `{decimals: N}` … 小数点以下 N 桁固定
- 省略時は有効数字 4 桁。どちらか一方のみ指定可

### 計算式で使える関数

| 分類 | 関数 |
|---|---|
| 要素ごと | `sqrt abs exp log log10 sin cos tan atan floor ceil round2(x,n)` |
| 集計 | `mean std`(標本, ddof=1)`pstd`(母, ddof=0)`sum min max count` |
| 最小二乗フィット | `slope(x,y) intercept(x,y) rvalue(x,y)`(y = a·x + b) |
| 定数 | `pi e` |

- 演算子: `+ - * / ** % //`
- **未入力(空欄)を含む列の集計・フィットは結果が「未確定(—)」になります**(未入力を黙って除外して平均する事故を防ぐため)
- 式は AST ホワイトリスト方式で安全に評価され、`__import__` や属性アクセスなどの危険な構文は使えません

## データの置き場所

```
reports/<report-id>/
  definition.yaml   # 計算方式(このファイルは AI/人間が用意)
  results.json      # 実験結果 + 計算キャッシュ(GUI が保存)
```

`reports/` はプレーンテキストなので git 管理できます。

## 開発

```bash
pip install -e ".[dev]"
pytest                 # 計算エンジン・丸め・CLI・API のテスト
```

計算エンジン(`resultsheet/engine/`)を中心にテストしています。特に `tests/test_rounding.py` は桁上がり・末尾ゼロ・指数表記の境界を、`tests/test_safe_eval.py` は危険な構文の拒否を検証します。
