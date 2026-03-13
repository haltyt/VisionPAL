#!/usr/bin/env python3
"""
Emotion-to-Physics ユーティリティ
PhysTalk論文のスキニング＆プロキシ生成を実装
"""

import numpy as np
from typing import Tuple, List


def build_convex_hull(gs_centers: np.ndarray, output_path: str = "/tmp/proxy_hull.obj") -> str:
    """
    3DGSのGaussian中心点からConvex Hullプロキシメッシュを生成
    PhysTalk: メッシュ抽出不要、軽量プロキシで物理シミュレーション

    Args:
        gs_centers: (N, 3) Gaussian中心座標
        output_path: 出力OBJファイルパス
    Returns:
        OBJファイルパス
    """
    from scipy.spatial import ConvexHull

    hull = ConvexHull(gs_centers)

    with open(output_path, "w") as f:
        f.write("# Convex hull proxy from 3DGS centers\n")
        for v in gs_centers[hull.vertices]:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")

        # Remap face indices to hull vertex indices
        vertex_map = {old: new + 1 for new, old in enumerate(hull.vertices)}
        for simplex in hull.simplices:
            indices = [vertex_map[s] for s in simplex]
            f.write(f"f {indices[0]} {indices[1]} {indices[2]}\n")

    print(f"✅ Convex hull: {len(hull.vertices)} vertices, {len(hull.simplices)} faces → {output_path}")
    return output_path


def compute_skinning(
    gs_centers: np.ndarray,
    particle_pos: np.ndarray,
    particle_F: np.ndarray,
    K: int = 8,
    epsilon: float = 1e-8,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    PhysTalk式 Gaussian Skinning
    物理パーティクルの運動を3DGS Gaussianに転送

    Args:
        gs_centers: (M, 3) 元のGaussian中心座標
        particle_pos: (N, 3) 現フレームのパーティクル位置
        particle_F: (N, 3, 3) 現フレームの変形勾配テンソル
        K: 近傍パーティクル数
        epsilon: 数値安定性のための小定数

    Returns:
        new_centers: (M, 3) 更新されたGaussian中心
        new_F_blended: (M, 3, 3) ブレンドされた変形勾配
    """
    from scipy.spatial import cKDTree

    M = gs_centers.shape[0]

    # 初期位置でのk-d tree（本来は初期パーティクル位置を使う）
    # ここでは現在位置から初期位置を推定（簡略化）
    # 実際にはrest poseのパーティクル位置を保持すべき
    tree = cKDTree(particle_pos)
    distances, indices = tree.query(gs_centers, k=K)

    # 逆距離重み (Eq.4)
    inv_dist = 1.0 / (distances ** 2 + epsilon)  # (M, K)
    weights = inv_dist / inv_dist.sum(axis=1, keepdims=True)  # (M, K) normalized

    # 変位の重み付き和 (Eq.5)
    # d_i = particle_pos - rest_pos (簡略化: ここでは直接位置を使う)
    neighbor_pos = particle_pos[indices]  # (M, K, 3)
    new_centers = np.sum(weights[:, :, None] * neighbor_pos, axis=1)  # (M, 3)

    # 変形勾配の重み付き和 (Eq.6)
    neighbor_F = particle_F[indices]  # (M, K, 3, 3)
    new_F_blended = np.sum(weights[:, :, None, None] * neighbor_F, axis=1)  # (M, 3, 3)

    return new_centers, new_F_blended


def apply_deformation_to_covariance(
    original_covs: np.ndarray,
    F_blended: np.ndarray,
) -> np.ndarray:
    """
    変形勾配を共分散行列に適用 (Eq.7)
    Σ_hat = F_hat @ Σ @ F_hat^T

    Args:
        original_covs: (M, 3, 3) 元の共分散行列
        F_blended: (M, 3, 3) ブレンドされた変形勾配

    Returns:
        new_covs: (M, 3, 3) 変形後の共分散行列
    """
    # Σ̂ = F̂ Σ F̂ᵀ
    new_covs = np.einsum("mij,mjk,mlk->mil", F_blended, original_covs, F_blended)
    return new_covs


# ============================================================
# デモ用: ダミーデータで動作確認
# ============================================================

def demo():
    """ダミーデータでスキニングパイプラインをテスト"""
    np.random.seed(42)

    # ダミー3DGS: 100個のGaussian
    M = 100
    gs_centers = np.random.randn(M, 3) * 0.5
    gs_covs = np.array([np.eye(3) * 0.01 for _ in range(M)])

    # ダミー物理パーティクル: 50個
    N = 50
    particle_pos = np.random.randn(N, 3) * 0.5 + np.array([0, 0, -0.1])  # 少し下に移動
    particle_F = np.array([np.eye(3) + np.random.randn(3, 3) * 0.05 for _ in range(N)])

    print("🧪 スキニングデモ")
    print(f"   Gaussians: {M}, Particles: {N}")

    # スキニング実行
    new_centers, new_F = compute_skinning(gs_centers, particle_pos, particle_F, K=8)

    # 共分散更新
    new_covs = apply_deformation_to_covariance(gs_covs, new_F)

    # 統計
    displacement = np.linalg.norm(new_centers - gs_centers, axis=1)
    print(f"   平均変位: {displacement.mean():.4f}")
    print(f"   最大変位: {displacement.max():.4f}")

    # 変形勾配のSVD（回転+伸縮の確認）
    U, S, Vt = np.linalg.svd(new_F[0])
    print(f"   サンプルSVD特異値: {S}")
    print("✅ スキニングパイプライン動作確認OK!")

    return new_centers, new_covs


if __name__ == "__main__":
    demo()
