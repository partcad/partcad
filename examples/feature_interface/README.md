# //pub/examples/partcad/feature_interface

This example demonstrates how the same parametrized assembly
can be defined in three slightly different ways
using three approaches to connect parts to each other.

## Usage
```shell
# placement == "outer"
pc inspect -a connect-ports
pc inspect -a connect-interfaces
pc inspect -a connect-mates

# placement == "inner"
pc inspect -a -p placement=inner connect-ports
pc inspect -a -p placement=inner connect-interfaces
pc inspect -a -p placement=inner connect-mates
```


## Assemblies

### connect-interfaces
<table><tr>
<td valign=top><a href="connect-interfaces.assy"><img src="././connect-interfaces.svg" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Demonstrates how to connect parts by specifying interfaces.</td>
<td valign=top>Parameters:<br/><ul>
<li>placement: <ul>
<li>inner</li><li><b>outer</b></li>
</ul>
</li>
<li>motor_tr_connect_to: <ul>
<li><b>TR</b></li>
<li>TL</li><li>BR</li><li>BL</li></ul>
</li>
</ul>
</td>
</tr></table>

### connect-mates
<table><tr>
<td valign=top><a href="connect-mates.assy"><img src="././connect-mates.svg" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Demonstrates how to provide the minimum information while letting PartCAD
determine the rest using the interfaces' mating metadata.
</td>
<td valign=top>Parameters:<br/><ul>
<li>placement: <ul>
<li>inner</li><li><b>outer</b></li>
</ul>
</li>
<li>motor_tr_connect_to: <ul>
<li><b>TR</b></li>
<li>TL</li><li>BR</li><li>BL</li></ul>
</li>
</ul>
</td>
</tr></table>

### connect-ports
<table><tr>
<td valign=top><a href="connect-ports.assy"><img src="././connect-ports.svg" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>Demonstrates how to connect parts by specifying ports.</td>
<td valign=top>Parameters:<br/><ul>
<li>placement: <ul>
<li>inner</li><li><b>outer</b></li>
</ul>
</li>
<li>motor_tr_connect_to: <ul>
<li><b>TR</b></li>
<li>TL</li><li>BR</li><li>BL</li></ul>
</li>
</ul>
</td>
</tr></table>

<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
