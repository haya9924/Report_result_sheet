---
name: resultsheet
description: >
  実験レポートの測定結果を LaTeX や文章にまとめるときに使う。resultsheet で
  管理された実験データ(reports フォルダ配下の definition.yaml と results.json)
  から、測定値・導出量・計算式・単位・誤差を取得して原稿に書く。数値を自分で
  計算・転記・丸めしてはならず、必ず CLI 出力の value/display を使う。実験の
  計算方式(definition.yaml)を新規作成・編集したり、結果入力後に誤差(不確かさ)
  の導出量を後から追加するときにも使う。「レポートの結果をまとめて」「実験結果を
  LaTeX に」「この測定値で」「誤差を出して」などの依頼で使用する。
---

# resultsheet スキル

実験レポートの数値を扱うシステム。**AI が測定値を読み間違えたり、丸めた値で
再計算して誤差バグを起こすのを防ぐ**ために作られている。このスキルはその防止策を
成立させるための AI 側の使い方を定める。

## 絶対規則(最優先)

1. **数値を自分で計算しない。** 平均・標準偏差・フィットの傾き・誤差などを暗算や
   手計算で出さない。すべて `definition.yaml` に式として書き、resultsheet に計算させる。
2. **数値を生データから読み取って転記しない。** LaTeX や文章に書く数値は、必ず
   `resultsheet get` / `resultsheet show --format json` の出力から取る。
3. **丸めは resultsheet に任せる。** 原稿に書く丸め済みの値は出力の `display`、
   さらに計算に使うフル精度値は `value`。自分で四捨五入しない。
4. **書く前に `resultsheet verify <report>` を実行**し、保存値と再計算が一致し
   (exit 0)ていることを確認する。NG なら数値を使わず、原因を報告する。

この規則を破ると、このシステムを使う意味がなくなる。

## コマンド(CUI)

`resultsheet` はデフォルトでカレントディレクトリ直下の `./reports/` を見る
(`resultsheet/cli.py` の `DEFAULT_REPORTS_DIR`)。そのため **`reports/` フォルダが
ある場所(通常はこのリポジトリのルート)で実行する**こと。別の場所からや
別パスの reports/ を使う場合は `--reports-dir <path>` を毎回明示する:

```bash
resultsheet --reports-dir /path/to/reports list
```

`resultsheet list` を実行して `(レポートはまだありません)` と出るのは、
`reports/` にまだ何も無い(ユーザーがまだブラウザで入力していない)だけで
異常ではない。その場合は `resultsheet serve` の起動を案内し、ユーザーの
入力を待つ。新規レポートの作成・値入力は CLI ではなく必ずブラウザ
(`resultsheet serve` → `http://127.0.0.1:8000/`)から行う — CLI に `new` の
ような作成コマンドは存在しない。

```bash
resultsheet list [--json]                     # レポート一覧
resultsheet show <report> --format json       # 全結果ダンプ(主要参照点)
resultsheet show <report> --format md         # 執筆用の表形式
resultsheet get  <report> <var> [--json]      # 1変数の value/display/unit/expr
resultsheet verify <report>                   # 保存値と再計算の一致検証(exit 0/1)
resultsheet validate <path.yaml>              # 定義YAMLの静的検証(exit 0/1)
resultsheet get-definition <report>           # 計算方式YAMLを取得
resultsheet set-definition <report> <path|->  # 計算方式を差し替え+既存入力で再計算
```

`show --format json` / `get --json` の各導出量は value(フル精度)と display
(丸め済み)を必ず併記する:

```json
"g_measured": {
  "value": 9.815362392947714,
  "display": "9.815",
  "unit": "m/s^2",
  "expr": "2 * a_slope",
  "rounding": {"sigfigs": 4}
}
```

→ LaTeX には `9.815` と `\mathrm{m/s^2}` を書き、さらに別の計算に使うときは
`value`(9.815362392947714)を式に入れる。

## 使い方: レポートの数値を原稿にまとめる

1. `resultsheet verify <report>` で整合を確認(exit 0)。
2. `resultsheet show <report> --format json` で全体を把握。
3. 各数値は `get <report> <var>` の `display`(本文用)/ `value`(再計算用)を使う。
   単位は `unit`、必要なら計算式は `expr` を根拠として引用できる。
4. 表は `show --format md` の表をそのまま流用してもよい。

## 使い方: 計算方式(definition.yaml)を新規作成する

ユーザーは「値を入力するだけ」にする。AI/ユーザーが計算方式を用意する。

- スキーマとサンプルは同梱テンプレート参照:
  `resultsheet/templates/density.yaml`(スカラー)、
  `resultsheet/templates/free_fall.yaml`(表+行内導出+集計+最小二乗フィット)、
  `resultsheet/templates/free_fall_error.yaml`(誤差評価つき)。
- 作ったら必ず `resultsheet validate <path.yaml>` で検証(exit 0)してから使う。
- GUI から作成する場合は `resultsheet serve` 後、ブラウザの「+ 新規レポート」で
  テンプレート選択・YAML 貼り付け・ファイル選択のいずれか。

### definition.yaml スキーマ要点

```yaml
meta: {id: <英数字_>, title: ..., description: ...}
constants: {k: {value: 2.5, unit: ..., description: ...}}   # 任意の固定値
inputs:                        # スカラー測定値(入力ボックス)
  - {name: m, label: 質量, unit: g, description: ..., display: {sigfigs: 3}}
tables:                        # 繰り返し測定(表)
  - name: drops
    label: 落下測定
    min_rows: 5
    columns: [{name: h, label: 落下距離, unit: m}, {name: t, label: 落下時間, unit: s}]
    derived_columns:           # 行ごとに計算(同じ表の列を裸名で参照)
      - {name: t2, expr: "t ** 2", unit: s^2, display: {sigfigs: 4}}
derived:                       # スカラー導出量。table.col で列全体を参照
  - {name: a_slope, expr: "slope(drops.t2, drops.h)", unit: m/s^2, display: {sigfigs: 4}}
  - {name: g, expr: "2 * a_slope", unit: m/s^2, display: {sigfigs: 4}}
```

- `display`: `{sigfigs: N}` か `{decimals: N}` のどちらか一方(省略時 有効数字4桁)。
- `range`: 妥当範囲 `{min, max, message?}`(片方だけでも可)。inputs・columns・
  derived・derived_columns に付けられる。**definition を作るときは、計測値と主要な
  計算結果に「誤差を考えてもあり得ない範囲以外」の緩い range を付けること。**
  値が範囲を外れると GUI では入力ボックスが赤くなって警告が出て、`show`/`get` でも
  報告される。範囲外でも入力・保存はブロックしない(あくまで警告)。
- 命名は全スコープで一意。未定義参照・循環依存・未知関数・未知キーは
  ロード時にエラーになる(AI 生成 YAML の typo 検出)。
- **未入力(空欄)を含む列の集計・フィットは結果が未確定(—)**になる。黙って除外しない。

原稿を書く前に `show --format json` の **`range_warnings`** を必ず確認する。範囲外の
値があれば、その数値をそのまま使わず、測定・入力ミスの可能性をユーザーに知らせる。

### 使える関数

| 分類 | 関数 |
|---|---|
| 要素ごと | `sqrt abs exp log log10 sin cos tan atan floor ceil round2(x,n)` |
| 集計 | `mean std`(標本,ddof=1)`pstd`(母)`sum min max count` |
| 誤差 | `sem(x)`(平均値の標準誤差)`slope_err(x,y) intercept_err(x,y)`(フィット係数の標準誤差) |
| 最小二乗フィット | `slope(x,y) intercept(x,y) rvalue(x,y)`(y = a·x + b) |
| 定数 | `pi e` |
| 演算子 | `+ - * / ** % //` |

式は AST ホワイトリスト方式で安全評価。`__import__`・添字・属性アクセス・
文字列・ラムダ等は使えない。

## 使い方: 結果入力後に誤差(不確かさ)を後から追加する

計算方式と結果は別ファイルなので、**結果入力後に導出量を足せば既存データに対して
再計算される**。CUI だけで完結する:

```bash
resultsheet get-definition <report> > def.yaml
# def.yaml の derived: に誤差の導出量を追記。例(自由落下の g):
#   - name: a_slope_err
#     expr: "slope_err(drops.t2, drops.h)"
#     unit: m/s^2
#     display: {sigfigs: 2}
#   - name: g_error
#     expr: "2 * a_slope_err"      # δg = 2·δa として伝播
#     unit: m/s^2
#     display: {sigfigs: 2}
resultsheet set-definition <report> def.yaml   # 差し替え+既存入力で再計算(検証NGなら元を保持)
resultsheet get <report> g_error               # 後付けした誤差を参照
resultsheet verify <report>                    # 整合確認
```

- 誤差伝播(例: ρ=m/V なら δρ=ρ·√((δm/m)²+(δV/V)²))は、不確かさを `inputs` に
  加えて `sqrt`・`**` で式に書く。
- フィットの傾き・切片の標準誤差は `slope_err` / `intercept_err`。
- `set-definition` は既存の入力値を保持したまま再計算・再保存するので `verify` は
  整合したまま。検証エラー時は書き込まず元の定義を保持する。

## やってはいけないこと

- 生データや results.json の数値を目視で読んで原稿に転記する。
- 平均・標準偏差・フィット・誤差を手計算する、または概算で書く。
- 出力の `display` をさらに丸める / `value` を勝手に四捨五入して式に入れる。
- `verify` が NG のまま数値を使う。
