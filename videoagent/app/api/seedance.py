"""API · Seedance Studio Pro."""


from .common import _fail, _ok


class SeedanceApi:
    # ------------------------------------------------------------------ Seedance Studio Pro
    def seedance_state(self) -> dict:
        return _ok(studio=self._seedance.snapshot())

    def seedance_action(self, action: str, data=None) -> dict:
        data = data or {}
        studio = self._seedance
        try:
            result = None
            if action == "config":
                result = studio.save_config(data)
            elif action == "import":
                result = studio.import_prompts(data.get("text", ""), data.get("filename", ""))
            elif action == "images":
                result = studio.import_images(data.get("paths", []))
            elif action == "image_data":
                result = studio.import_image_data(data.get("name", ""), data.get("dataUrl", ""))
            elif action == "job":
                studio.change_job(data["id"], data["action"], data.get("text", ""))
            elif action == "image":
                studio.change_image(data["id"], data["action"])
            elif action == "start":
                result = studio.start(data.get("config", {}), data.get("ids"))
            elif action == "history":
                result = studio.start(data.get("config", {}), history_url=data.get("url", ""))
            elif action == "stop":
                studio.stop()
            elif action == "download":
                studio.download(data["id"])
            elif action == "watermark":
                studio.remove_watermark(data["id"], data.get("rectangle", {}))
            elif action == "open":
                studio.open_media(data["id"])
            elif action == "link":
                studio.link_media(data["id"], data["sceneId"])
            elif action == "zip":
                studio.export_zip(data.get("ids"))
            elif action == "export":
                result = studio.export_project()
            else:
                raise ValueError("Thao tác Studio không hợp lệ")
            return _ok(result=result, studio=studio.snapshot())
        except Exception as exc:
            return _fail(exc)
