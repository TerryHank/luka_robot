"""Explicitly refuse NX-only NanoOWL queries on S100."""


class ModelRuntime:
    def __init__(self, root):
        self.root = root

    def locate(self, image, query, prefix):
        raise ValueError(
            "S100 当前只支持 BPU 固定类别寻物；描述、颜色和关系词需要另行部署开放词表模型"
        )

    def unload(self):
        return None

    def loaded(self):
        return False
