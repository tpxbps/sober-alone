"""Long-lived caching only for immutable clue resource derivatives."""

import re

from starlette.staticfiles import StaticFiles

_CONTENT_ADDRESSED_CLUE = re.compile(r"scripts/[^/]+/clues/asset-[0-9a-f]{64}\.webp")


class ImageStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # Other runtime images may be replaced in place; keep their existing policy.
        immutable = _CONTENT_ADDRESSED_CLUE.fullmatch(path.replace("\\", "/"))
        if immutable and response.status_code in (200, 206):
            # Platform MIME registries can omit or misclassify WebP.
            response.headers["Content-Type"] = "image/webp"
        if immutable and response.status_code in (200, 206, 304):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
