"""Small, explicit scene language. Distances: meters; rotations: degrees; Z up."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[float, Field(allow_inf_nan=False, ge=-1e7, le=1e7)]
Vec3 = tuple[Number, Number, Number]
Color = tuple[Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)]]
Id = Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")]

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Material(Model):
    id: Id
    color: Color = (0.5, 0.65, 0.8, 1)
    metallic: float = Field(default=0, ge=0, le=1)
    roughness: float = Field(default=0.35, ge=0, le=1)
    emission: float = Field(default=0, ge=0, le=100)

class Keyframe(Model):
    frame: int = Field(ge=1, le=100000)
    location: Vec3 | None = None
    rotation: Vec3 | None = None
    scale: Vec3 | None = None

class Modifier(Model):
    type: Literal["bevel", "subdivision", "solidify", "mirror", "decimate"]
    amount: float = Field(default=0.05, ge=0, le=100)
    levels: int = Field(default=1, ge=0, le=3)
    ratio: float = Field(default=0.5, gt=0, le=1)

class ObjectSpec(Model):
    id: Id
    type: Literal["cube", "sphere", "cylinder", "cone", "torus", "plane", "mesh", "empty", "import"] = "cube"
    location: Vec3 = (0, 0, 0)
    rotation: Vec3 = (0, 0, 0)
    scale: Vec3 = (1, 1, 1)
    parent: Id | None = None
    material: Id | None = None
    smooth: bool = True
    preview_hidden: bool = False
    asset: str | None = Field(default=None, max_length=200)
    vertices: list[Vec3] = Field(default_factory=list, max_length=100000)
    faces: list[list[int]] = Field(default_factory=list, max_length=100000)
    modifiers: list[Modifier] = Field(default_factory=list, max_length=8)
    keyframes: list[Keyframe] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def valid_mesh(self):
        if self.type == "import" and not self.asset:
            raise ValueError("import requires asset returned by import_asset")
        if self.type == "mesh":
            if not self.vertices or not self.faces:
                raise ValueError("mesh needs vertices and faces")
            for face in self.faces:
                if len(face) < 3 or len(face) > 1000 or any(i < 0 or i >= len(self.vertices) for i in face):
                    raise ValueError("mesh face has invalid vertex indices or size")
        frames = [k.frame for k in self.keyframes]
        if len(set(frames)) != len(frames):
            raise ValueError("duplicate keyframe numbers")
        return self

class Camera(Model):
    location: Vec3 = (7, -9, 6)
    target: Vec3 = (0, 0, 1)
    lens: float = Field(default=48, ge=1, le=300)

class Light(Model):
    id: Id
    type: Literal["AREA", "SUN", "POINT"] = "AREA"
    location: Vec3 = (3, -4, 7)
    target: Vec3 = (0, 0, 0)
    energy: float = Field(default=1000, ge=0, le=100000)
    size: float = Field(default=5, gt=0, le=100)
    color: tuple[Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)]] = (1, 1, 1)

class SceneSpec(Model):
    name: str = Field(default="Untitled", max_length=200)
    objects: list[ObjectSpec] = Field(default_factory=list, max_length=2000)
    materials: list[Material] = Field(default_factory=list, max_length=500)
    camera: Camera = Field(default_factory=Camera)
    lights: list[Light] = Field(default_factory=lambda: [Light(id="key")], max_length=64)
    world_color: tuple[Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)]] = (0.08, 0.1, 0.14)
    fps: int = Field(default=24, ge=1, le=120)
    frame_end: int = Field(default=120, ge=1, le=100000)

    @model_validator(mode="after")
    def references(self):
        ids = [o.id for o in self.objects]
        mats = [m.id for m in self.materials]
        lights = [l.id for l in self.lights]
        if len(ids) != len(set(ids)) or len(mats) != len(set(mats)) or len(lights) != len(set(lights)):
            raise ValueError("IDs must be unique within each collection")
        parents = {o.id: o.parent for o in self.objects}
        for obj in self.objects:
            if obj.material and obj.material not in mats:
                raise ValueError(f"Unknown material: {obj.material}")
            if obj.parent and obj.parent not in parents:
                raise ValueError(f"Unknown parent: {obj.parent}")
            seen = {obj.id}
            parent = obj.parent
            while parent:
                if parent in seen:
                    raise ValueError("Parent cycle")
                seen.add(parent)
                parent = parents.get(parent)
            if any(k.frame > self.frame_end for k in obj.keyframes):
                raise ValueError("Keyframe exceeds frame_end")
        return self

class RenderOptions(Model):
    enabled: bool = False
    engine: Literal["CYCLES", "BLENDER_EEVEE"] = "CYCLES"
    width: int = Field(default=960, ge=64, le=4096)
    height: int = Field(default=720, ge=64, le=4096)
    samples: int = Field(default=32, ge=1, le=1024)
    frames: list[Annotated[int, Field(ge=1, le=100000)]] = Field(default_factory=lambda: [1], min_length=1, max_length=240)

class BuildRequest(Model):
    scene: SceneSpec
    expected_revision: str | None = None
    render: RenderOptions = Field(default_factory=RenderOptions)

class PatchRequest(Model):
    expected_revision: str
    upsert_objects: list[ObjectSpec] = Field(default_factory=list, max_length=2000)
    delete_objects: list[Id] = Field(default_factory=list)
    upsert_materials: list[Material] = Field(default_factory=list, max_length=500)
    render: RenderOptions = Field(default_factory=RenderOptions)
