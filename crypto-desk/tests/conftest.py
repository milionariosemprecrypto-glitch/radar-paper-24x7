# Fase 7: nunca deixar testes tocarem o banco de produção (app.state cria STORE no import).
import os, tempfile
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="desk-test-"), "test.sqlite"))
