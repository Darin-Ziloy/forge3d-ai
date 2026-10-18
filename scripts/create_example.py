"""Generate the included demo scene without external model assets."""
import json
from pathlib import Path

objects = []
def add(id, type, location, scale=(1,1,1), material=None, **kwargs):
    objects.append(dict(id=id, type=type, location=location, scale=scale, material=material, **kwargs))

add("drone", "empty", [0,0,2.5], keyframes=[{"frame":1,"rotation":[0,0,-20],"location":[0,0,2.5]},{"frame":61,"rotation":[0,0,160],"location":[0,0,2.75]},{"frame":121,"rotation":[0,0,340],"location":[0,0,2.5]}])
add("shell", "sphere", [0,0,0], [1.1,.75,.7], "ceramic", parent="drone")
add("visor", "sphere", [0,-.58,.05], [.82,.31,.43], "obsidian", parent="drone")
for x, label in [(-.34,"left"),(.34,"right")]:
    add("lens_"+label,"sphere",[x,-.86,.1],[.14,.055,.14],"mint",parent="drone")
    add("wing_"+label,"cube",[x*4,0,-.06],[.36,.48,.07],"ceramic",parent="drone",modifiers=[{"type":"bevel","amount":.2}])
    add("thruster_"+label,"cylinder",[x*4,0,-.2],[.24,.24,.13],"obsidian",parent="drone")
    add("thruster_glow_"+label,"torus",[x*4,0,-.34],[.18,.18,.18],"mint",parent="drone")
add("antenna","cylinder",[0,.05,.85],[.035,.035,.23],"alloy",parent="drone")
add("beacon","sphere",[0,.05,1.1],[.1,.1,.1],"orange",parent="drone")
add("orbit_ring","torus",[0,0,-.05],[1.72,1.25,.25],"alloy",parent="drone",rotation=[12,8,0])
add("badge","cube",[0,-.66,-.35],[.15,.07,.035],"orange",parent="drone",modifiers=[{"type":"bevel","amount":.2}])
add("pedestal","cylinder",[0,0,.14],[1.6,1.6,.14],"obsidian",modifiers=[{"type":"bevel","amount":.12}])
add("pedestal_trim","torus",[0,0,.27],[1.32,1.32,.16],"mint")
add("ground","plane",[0,0,-.01],[100,100,100],"ground_mat",preview_hidden=True)
scene = {
 "name":"Orbital / inspection drone", "fps":24, "frame_end":121,
 "camera":{"location":[6,-10,6],"target":[0,0,1.9],"lens":52},
 "world_color":[.12,.16,.14],
 "lights":[{"id":"key","location":[3,-4,7],"energy":1300,"size":5},{"id":"rim","location":[-4,3,6],"energy":1800,"size":4,"color":[.65,.9,1]},{"id":"fill","location":[-4,-3,2],"energy":650,"size":3}],
 "materials":[{"id":"ceramic","color":[.63,.72,.65,1],"metallic":.28,"roughness":.28},{"id":"obsidian","color":[.018,.03,.026,1],"metallic":.45,"roughness":.25},{"id":"alloy","color":[.27,.4,.32,1],"metallic":.8,"roughness":.24},{"id":"mint","color":[.43,1,.5,1],"emission":2.2,"roughness":.3},{"id":"orange","color":[1,.21,.045,1],"emission":.6},{"id":"ground_mat","color":[.075,.11,.085,1],"roughness":.85}],
 "objects":objects
}
path = Path(__file__).resolve().parent.parent / "examples" / "orbital-bot.json"
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(scene, indent=2), encoding="utf-8")
print(path)
