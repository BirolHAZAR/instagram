"""Celery task paket kayıt noktası.

Yeni profesyonel ana task modülleri:
- sync_tasks.py
- metric_tasks.py
- notification_tasks.py
- analysis_tasks.py
- budget_tasks.py
- maintenance_tasks.py
- report_tasks.py

Eski task dosyaları geriye uyumluluk için projede kalabilir.
Yeni Beat schedule ve yeni kodlar bu dosyaları kullanmalıdır.
"""

from . import sync_tasks  # noqa: F401
from . import metric_tasks  # noqa: F401
from . import notification_tasks  # noqa: F401
from . import analysis_tasks  # noqa: F401
from . import budget_tasks  # noqa: F401
from . import maintenance_tasks  # noqa: F401
from . import report_tasks  # noqa: F401
from . import marketplace_sync  # noqa: F401
from . import competitor_sync  # noqa: F401
from . import control_tower_ai  # noqa: F401
from . import admin_ops  # noqa: F401
from . import organic_publish  # noqa: F401
from . import communications  # noqa: F401
