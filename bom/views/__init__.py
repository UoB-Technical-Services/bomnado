""" The views, one module per area. `from bom import views` keeps working: everything
public is re-exported here, which is what bom/urls.py resolves against. """
from bom.views.shared import *  # noqa: F401,F403
from bom.views.parts import *  # noqa: F401,F403
from bom.views.library import *  # noqa: F401,F403
from bom.views.assemblies import *  # noqa: F401,F403
from bom.views.dashboard import *  # noqa: F401,F403
from bom.views.teams import *  # noqa: F401,F403
from bom.views.tools import *  # noqa: F401,F403
from bom.views.exports import *  # noqa: F401,F403
from bom.views.attachments import *  # noqa: F401,F403
from bom.views.activity import *  # noqa: F401,F403
from bom.views.ai import *  # noqa: F401,F403
