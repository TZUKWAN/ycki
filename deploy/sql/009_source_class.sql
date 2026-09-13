-- 009: resources.source_class — Source Strategy Engine 的来源类溯源（§5）
ALTER TABLE resources ADD COLUMN IF NOT EXISTS source_class TEXT DEFAULT 'GeneralWebsite';
