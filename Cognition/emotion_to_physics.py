#!/usr/bin/env python3
"""
Emotion-to-Physics Translator (PhysTalk × VisionPAL)
Survival Engineの欲求値 → LLMで物理シミュレーションコード生成 → Genesis実行

使い方:
  # コード生成のみ（Genesis不要）
  uv run -p 3.12 emotion_to_physics.py --dry-run

  # Genesis実行（PC側、pip install genesis-world 必要）
  uv run -p 3.12 emotion_to_physics.py --run

  # カスタム欲求値
  uv run -p 3.12 emotion_to_physics.py --dry-run --hunger 0.8 --curiosity 0.2 --loneliness 0.9
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict

# ============================================================
# Survival Engine 欲求モデル（VisionPALから抜粋）
# ============================================================

@dataclass
class Needs:
    hunger: float = 0.5      # 空腹 (0=満腹, 1=飢餓)
    curiosity: float = 0.5   # 好奇心 (0=退屈, 1=興奮)
    loneliness: float = 0.5  # 孤独 (0=満足, 1=孤独)
    fatigue: float = 0.3     # 疲労 (0=元気, 1=疲弊)
    anxiety: float = 0.2     # 不安 (0=安心, 1=恐怖)

    def dominant_emotion(self) -> str:
        """最も強い欲求から感情を決定"""
        scores = {
            "melting":    self.loneliness * 0.7 + self.fatigue * 0.3,
            "exploding":  self.anxiety * 0.6 + self.hunger * 0.4,
            "floating":   self.curiosity * 0.8 + (1 - self.fatigue) * 0.2,
            "crumbling":  self.fatigue * 0.6 + self.loneliness * 0.4,
            "bouncing":   self.curiosity * 0.5 + (1 - self.anxiety) * 0.5,
        }
        return max(scores, key=scores.get)

    def physics_prompt(self) -> str:
        """欲求値から物理プロンプトを生成"""
        emotion = self.dominant_emotion()
        prompts = {
            "melting":   f"The object slowly melts into a viscous fluid, losing its form. Gravity is {0.5 + self.loneliness * 1.5:.1f}x normal.",
            "exploding": f"The object shatters into rigid fragments with explosive force {self.anxiety * 200:.0f}N outward.",
            "floating":  f"The object defies gravity, floating upward with gentle rotation. Gravity is inverted at {self.curiosity * 0.3:.2f}x.",
            "crumbling": f"The object crumbles under its own weight, pieces falling with {9.8 + self.fatigue * 10:.1f} m/s² gravity.",
            "bouncing":  f"The object is elastic and bouncy, dropping from height 2m with restitution {0.5 + self.curiosity * 0.4:.2f}.",
        }
        return prompts[emotion]


# ============================================================
# PhysTalk式 テンプレート制約プロンプト
# ============================================================

SYSTEM_PROMPT = """You are a physics simulation code generator for the Genesis engine.
You MUST fill in the provided template functions. Do NOT write code outside the template.
Use ONLY the Genesis API documented below.

## Genesis API Reference (subset)
```python
import genesis as gs
gs.init(backend=gs.cuda)

scene = gs.Scene(
    sim_options=gs.options.SimOptions(dt=1/60, gravity=(0, 0, -9.8)),
    mpm_options=gs.options.MPMOptions(lower_bound=(x,y,z), upper_bound=(x,y,z)),
    vis_options=gs.options.VisOptions(show_world_frame=False),
)

# Materials
mat_elastic = gs.materials.MPM.Muscle(E=1e4, nu=0.3, rho=1000)
mat_rigid   = gs.materials.MPM.Liquid(E=1e6, nu=0.4, rho=2000, viscosity=0.0)
mat_fluid   = gs.materials.SPH.Liquid(rho=1000, viscosity=0.01)

# Add objects
obj = scene.add_entity(
    morph=gs.morphs.Mesh(file="mesh.obj", scale=1.0, pos=(0,0,0)),
    material=mat_elastic,
)
plane = scene.add_entity(gs.morphs.Plane())

scene.build()
scene.step()  # advance one timestep
```

## Custom API (pre-provided, just call these)
- `compute_skinning(gs_centers, particle_pos, particle_F, K=8)` → returns (new_centers, new_covs)
- `build_convex_hull(gs_centers)` → returns mesh path for proxy

## Rules
- Always add a ground plane
- Keep gravity physically plausible unless the prompt says otherwise
- Set dt=1/120 for stability
- Use MPM.Muscle for elastic, MPM.Liquid for rigid-like, SPH.Liquid for fluids
- Do NOT use features not in the API above
- Output ONLY the three functions, no explanations
"""

CODE_TEMPLATE = """
## Fill in these three functions based on the user's prompt:

```python
def build_scene(gs_centers):
    \"\"\"
    Create the Genesis scene with appropriate materials and objects.
    gs_centers: numpy array (N, 3) of Gaussian centers
    Returns: (scene, entity)
    \"\"\"
    # YOUR CODE HERE
    pass

def step(scene, entity, num_steps=120):
    \"\"\"
    Run simulation and record particle positions + deformation gradients.
    Returns: (positions_list, F_list) - lists of arrays per frame
    \"\"\"
    # YOUR CODE HERE
    pass

def query(gs_centers, gs_covs, positions_list, F_list):
    \"\"\"
    Apply skinning to transfer physics to Gaussians.
    Returns: list of (new_centers, new_covs) per frame
    \"\"\"
    # YOUR CODE HERE
    pass
```
"""


def generate_physics_code(needs: Needs, use_api: bool = False) -> str:
    """LLMでGenesis物理コードを生成（APIなしの場合はルールベースで生成）"""

    emotion = needs.dominant_emotion()
    prompt = needs.physics_prompt()

    if use_api:
        # OpenAI API経由でLLM生成
        try:
            from openai import OpenAI

            env_path = os.path.expanduser("~/.openclaw/workspace/.env.openai")
            api_key = None
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        if line.startswith("OPENAI_API_KEY="):
                            api_key = line.strip().split("=", 1)[1]
            if not api_key:
                api_key = os.environ.get("OPENAI_API_KEY")

            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Prompt: {prompt}\n\n{CODE_TEMPLATE}"},
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            return resp.choices[0].message.content

        except Exception as e:
            print(f"⚠️ LLM API失敗、ルールベースにフォールバック: {e}", file=sys.stderr)

    # ルールベースのコード生成（LLM不要版）
    return _rule_based_code(emotion, needs)


def _rule_based_code(emotion: str, needs: Needs) -> str:
    """ルールベースでGenesisコードを生成（デモ用）"""

    configs = {
        "melting": {
            "material": "gs.materials.SPH.Liquid(rho=1000, viscosity={:.3f})".format(
                0.1 - needs.loneliness * 0.08
            ),
            "gravity": (0, 0, -9.8 * (0.5 + needs.loneliness * 1.5)),
            "description": "# 孤独 → 溶解: 形を失っていく",
        },
        "exploding": {
            "material": "gs.materials.MPM.Liquid(E=1e6, nu=0.4, rho=2000, viscosity=0.0)",
            "gravity": (0, 0, -9.8),
            "force": needs.anxiety * 200,
            "description": "# 不安 → 爆発: 内側から砕ける",
        },
        "floating": {
            "material": "gs.materials.MPM.Muscle(E=5e3, nu=0.3, rho=500)",
            "gravity": (0, 0, 9.8 * needs.curiosity * 0.3),
            "description": "# 好奇心 → 浮遊: 重力に逆らう",
        },
        "crumbling": {
            "material": "gs.materials.MPM.Muscle(E=2e3, nu=0.45, rho=1500)",
            "gravity": (0, 0, -(9.8 + needs.fatigue * 10)),
            "description": "# 疲労 → 崩壊: 自重に耐えられない",
        },
        "bouncing": {
            "material": "gs.materials.MPM.Muscle(E=1e4, nu=0.3, rho=800)",
            "gravity": (0, 0, -9.8),
            "description": "# 好奇心+安心 → 弾む: エネルギッシュ",
        },
    }

    cfg = configs[emotion]
    gx, gy, gz = cfg["gravity"]

    code = f'''
{cfg["description"]}
# 感情: {emotion} | 欲求値: {json.dumps(asdict(needs), ensure_ascii=False)}

import genesis as gs
import numpy as np
from emotion_to_physics_utils import compute_skinning, build_convex_hull

def build_scene(gs_centers):
    gs.init(backend=gs.cuda)

    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1/120, gravity=({gx}, {gy}, {gz})),
        mpm_options=gs.options.MPMOptions(
            lower_bound=(-1, -1, -0.5),
            upper_bound=(1, 1, 2),
        ),
        vis_options=gs.options.VisOptions(show_world_frame=False),
    )

    # Ground plane
    plane = scene.add_entity(gs.morphs.Plane())

    # Object proxy from Gaussian centers
    mesh_path = build_convex_hull(gs_centers)
    material = {cfg["material"]}
    entity = scene.add_entity(
        morph=gs.morphs.Mesh(file=mesh_path, scale=1.0, pos=(0, 0, 0.5)),
        material=material,
    )

    scene.build()
    return scene, entity


def step(scene, entity, num_steps=240):
    positions_list = []
    F_list = []

    for i in range(num_steps):
        scene.step()
        pos = entity.get_state().pos.cpu().numpy()
        F = entity.get_state().F.cpu().numpy()
        positions_list.append(pos)
        F_list.append(F)

    return positions_list, F_list


def query(gs_centers, gs_covs, positions_list, F_list):
    frames = []
    for pos, F in zip(positions_list, F_list):
        new_centers, new_covs = compute_skinning(gs_centers, pos, F, K=8)
        frames.append((new_centers, new_covs))
    return frames
'''

    # 爆発の場合は外向き力を追加
    if emotion == "exploding":
        force_code = f'''
    # Apply explosive force at frame 0
    # entity.apply_external_force(force=({cfg["force"]:.0f}, 0, {cfg["force"]:.0f}))
'''
        code = code.replace("    scene.build()", force_code + "    scene.build()")

    return code


# ============================================================
# メイン
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Emotion-to-Physics (PhysTalk × VisionPAL)")
    parser.add_argument("--hunger", type=float, default=0.5)
    parser.add_argument("--curiosity", type=float, default=0.5)
    parser.add_argument("--loneliness", type=float, default=0.5)
    parser.add_argument("--fatigue", type=float, default=0.3)
    parser.add_argument("--anxiety", type=float, default=0.2)
    parser.add_argument("--dry-run", action="store_true", help="コード生成のみ（Genesis不要）")
    parser.add_argument("--use-llm", action="store_true", help="LLM APIでコード生成")
    parser.add_argument("--run", action="store_true", help="Genesisで実行")
    parser.add_argument("--ply", type=str, help="入力.plyファイル（3DGS）")
    args = parser.parse_args()

    needs = Needs(
        hunger=args.hunger,
        curiosity=args.curiosity,
        loneliness=args.loneliness,
        fatigue=args.fatigue,
        anxiety=args.anxiety,
    )

    emotion = needs.dominant_emotion()
    prompt = needs.physics_prompt()

    print("=" * 60)
    print("🧠 Survival Engine → Emotion-to-Physics")
    print("=" * 60)
    print(f"欲求値: {json.dumps(asdict(needs), indent=2, ensure_ascii=False)}")
    print(f"支配的感情: {emotion}")
    print(f"物理プロンプト: {prompt}")
    print("=" * 60)

    code = generate_physics_code(needs, use_api=args.use_llm)
    print("\n📝 生成されたGenesisコード:")
    print(code)

    if args.dry_run:
        # コードをファイルに保存
        out_path = f"generated_physics_{emotion}.py"
        with open(out_path, "w") as f:
            f.write(code)
        print(f"\n✅ 保存: {out_path}")
        print("💡 PCで実行するには: pip install genesis-world && python " + out_path)
        return

    if args.run:
        print("\n🚀 Genesis実行...")
        try:
            import genesis as gs
            # TODO: PLY読み込み → build_scene → step → query → フレーム出力
            print("⚠️ Genesis実行は未実装。PCで直接スクリプトを実行してください。")
        except ImportError:
            print("❌ genesis-world がインストールされていません")
            print("   pip install genesis-world")
            sys.exit(1)


if __name__ == "__main__":
    main()
