
# 孤独 → 溶解: 形を失っていく
# 感情: melting | 欲求値: {"hunger": 0.5, "curiosity": 0.1, "loneliness": 0.9, "fatigue": 0.6, "anxiety": 0.2}

import genesis as gs
import numpy as np
from emotion_to_physics_utils import compute_skinning, build_convex_hull

def build_scene(gs_centers):
    gs.init(backend=gs.cuda)

    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1/120, gravity=(0, 0, -18.130000000000003)),
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
    material = gs.materials.SPH.Liquid(rho=1000, viscosity=0.028)
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
