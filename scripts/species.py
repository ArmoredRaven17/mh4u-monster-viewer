"""Each monster's species (the Species Type dropdown) and large / small -- KEPT BY HAND for now.

The 3U viewer reads both from the executable's Monster List table. No such table has been found in
4U's code yet: no per-monster byte at any stride groups the monster numbers the way their species do,
and no (monster, type) row table in list order turned up either (scratch scans, 2026-10-08), which
matches the MH4U Quest Randomizer's experience (its MONSTER_CLASS is hand-kept too). So:

  * the species NAMES and their ORDER are the game's own: HunterNote 22-35 (core_common msg, LMD),
    the type line of the Hunter's Notes; 20 is its "???" (Gore Magala).
  * which monster has which species is hand-kept: the large monsters are the MH4U Quest Randomizer's
    MONSTER_CLASS (by name), the small ones are kept here. A monster in neither is an error at build
    time, so a rebuild cannot silently leave one out.
"""
import os, sys

sys.path.insert(0, r'C:\Coding Repos\mh4u-armor-viewer\scripts')
import mh4u

HN = mh4u.lmd_messages(os.path.join('common', 'HunterNote'))
ORDER = [HN[i] for i in range(22, 36)] + [HN[20]]          # Flying Wyvern ... Carapaceon, ???

LARGE = {
    'Flying Wyvern': ['Rathian', 'Pink Rathian', 'Gold Rathian', 'Rathalos', 'Azure Rathalos',
                      'Silver Rathalos', 'Tigrex', 'Brute Tigrex', 'Molten Tigrex', 'Apex Tigrex',
                      'Khezu', 'Red Khezu', 'Basarios', 'Ruby Basarios', 'Gravios', 'Black Gravios',
                      'Apex Gravios', 'Diablos', 'Black Diablos', 'Apex Diablos', 'Monoblos',
                      'White Monoblos', 'Seregios', 'Apex Seregios', 'Akantor', 'Ukanlos'],
    'Bird Wyvern': ['Yian Kut-Ku', 'Blue Yian Kut-Ku', 'Gypceros', 'Purple Gypceros', 'Yian Garuga',
                    'Great Jaggi', 'Velocidrome', 'Gendrome', 'Iodrome'],
    'Fanged Beast': ['Congalala', 'Emerald Congalala', 'Rajang', 'Furious Rajang', 'Apex Rajang',
                     'Kecha Wacha', 'Ash Kecha Wacha', 'Lagombi'],
    'Amphibian': ['Tetsucabra', 'Berserk Tetsucabra', 'Zamtrios', 'Tigerstripe Zamtrios'],
    'Snake Wyvern': ['Najarala', 'Tidal Najarala', 'Apex Tidal Najarala', 'Dalamadur', 'Shah Dalamadur'],
    'Elder Dragon': ['Kushala Daora', 'Rusted Kushala Daora', 'Teostra', 'Chameleos', 'Kirin',
                     'Oroshi Kirin', 'Shagaru Magala', "Dah'ren Mohran", 'Fatalis', 'Crimson Fatalis',
                     'White Fatalis', 'G Rank Crimson Fatalis', 'Gogmazios'],
    'Neopteron': ['Seltas', 'Desert Seltas', 'Seltas Queen', 'Desert Seltas Queen'],
    'Temnoceran': ['Nerscylla', 'Shrouded Nerscylla'],
    'Brute Wyvern': ['Deviljho', 'Savage Deviljho', 'Apex Deviljho', 'Brachydios', 'Raging Brachydios'],
    'Fanged Wyvern': ['Zinogre', 'Stygian Zinogre', 'Apex Zinogre'],
    'Piscine Wyvern': ['Cephadrome'],
    'Carapaceon': ['Daimyo Hermitaur', 'Plum D.Hermitaur'],
    '???': ['Gore Magala', 'Chaotic Gore Magala'],
}
SMALL = {
    'Herbivore': ['Aptonoth', 'Apceros', 'Kelbi', 'Popo', 'Slagtoth', 'Rhenoplos', 'Gargwa'],
    'Lynian': ['Felyne', 'Melynx'],
    'Bird Wyvern': ['Jaggi', 'Jaggia', 'Velociprey', 'Genprey', 'Ioprey'],
    'Fanged Beast': ['Conga'],
    'Snake Wyvern': ['Remobra'],
    'Piscine Wyvern': ['Delex', 'Cephalos'],
    'Neopteron': ['Altaroth', 'Bnahabra', 'Konchu'],
    'Amphibian': ['Zamite'],
    'Carapaceon': ['Hermitaur'],
}
for table in (LARGE, SMALL):
    for k in table:
        assert k in ORDER, k

ABOUT = ('HAND-KEPT, not read from the game: no Monster List table has been found in 4U\'s code (3U\'s '
         'is). The species names and their order are the game\'s own -- HunterNote 22-35, the Hunter\'s '
         'Notes type line, and 20 ("???") for Gore Magala -- but which monster has which is the MH4U '
         'Quest Randomizer\'s hand-kept MONSTER_CLASS for the large monsters and this app\'s '
         'scripts/species.py for the small ones. `small` is hand-kept the same way; `speciesFrom` is '
         '"hand" on every row so nothing passes for ROM data.')


def of(name, em):
    base = name.split(' (')[0]
    for small, table in ((False, LARGE), (True, SMALL)):
        for sp, names in table.items():
            if base in names:
                return {'species': sp, 'speciesAbbr': None, 'speciesIdx': ORDER.index(sp),
                        'speciesFrom': 'hand', 'small': small, 'listSection': None, 'listRank': None}
    return {'species': None, 'speciesAbbr': None, 'speciesIdx': None, 'speciesFrom': None,
            'small': None, 'listSection': None, 'listRank': None}
