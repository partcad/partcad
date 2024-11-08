# %%

# The markers "# %%" separate code blocks for execution (cells)
# Press shift-enter to exectute a cell and move to next cell
# Press ctrl-enter to exectute a cell and keep cursor at the position
# For more details, see https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter

# %%

from build123d import *
from ocp_vscode import *

# %%
# Builder mode

with BuildPart() as bp:
    Box(1,1,1)
    fillet(bp.edges(), radius=0.1)

show(bp)

# %%
# Algebra mode

b2 = Box(1,2,3)
b2 = fillet(b2.edges(), 0.1)

show(b2, axes=True, axes0=True, grid=(True, True, True), transparent=True)

# %%
