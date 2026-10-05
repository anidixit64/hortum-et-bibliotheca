from hortum_common import create_app
from service_a import routes
from service_a.config import get_settings

app = create_app(get_settings(), [routes.router])
