from direct.task import Task


class ShadowMixin:
    def setup_blob_shadows(self):
        self.brick_blob_shadows = {}
        self.char_shadows = []

    def create_brick_blob_shadow(self, brick):
        pass

    def remove_brick_blob_shadow(self, brick):
        pass

    def _bake_brick_shadows(self):
        pass

    def update_blob_shadows_task(self, task):
        return Task.cont
