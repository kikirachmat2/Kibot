
import os

def find_unused_in_file(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    content = "".join(lines)
    
    # Simple check for unused private members
    private_members = []
    for line in lines:
        line = line.strip()
        if line.startswith('private val') or line.startswith('private var') or line.startswith('private fun') or line.startswith('private const val'):
            name = ""
            if 'val ' in line:
                name = line.split('val ')[1].split(':')[0].split('=')[0].strip()
            elif 'var ' in line:
                name = line.split('var ')[1].split(':')[0].split('=')[0].strip()
            elif 'fun ' in line:
                name = line.split('fun ')[1].split('(')[0].strip()
            
            if name and name not in ['toExecutionPlan', 'toPositionHorizon', 'toExecutionSide', 'toPriceStep', 'toQuantityStep']: # keep these for now
                private_members.append(name)
    
    unused = []
    for member in private_members:
        if content.count(member) == 1:
            unused.append(member)
            
    return unused

filepath = '/Users/kiki/Documents/Web Develop/KiBot/Shared/packages/core/src/commonMain/kotlin/com/kibot/core/StrategyOrchestrator.kt'
unused = find_unused_in_file(filepath)
print(f"Unused private members in {filepath}:")
for u in unused:
    print(u)
