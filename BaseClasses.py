from __future__ import annotations

import copy
from enum import Enum, unique
import logging
import json
import functools
from collections import OrderedDict, Counter, deque
from typing import List, Dict, Optional, Set, Iterable, Union, Any, Tuple
import secrets
import random

import Options
import Utils


class MultiWorld():
    debug_types = False
    player_name: Dict[int, str]
    _region_cache: Dict[int, Dict[str, Region]]
    difficulty_requirements: dict
    required_medallions: dict
    dark_room_logic: Dict[int, str]
    restrict_dungeon_item_on_boss: Dict[int, bool]
    plando_texts: List[Dict[str, str]]
    plando_items: List
    plando_connections: List
    worlds: Dict[int, Any]
    is_race: bool = False
    precollected_items: Dict[int, List[Item]]

    class AttributeProxy():
        def __init__(self, rule):
            self.rule = rule

        def __getitem__(self, player) -> bool:
            return self.rule(player)

    def __init__(self, players: int):
        self.random = random.Random()  # world-local random state is saved for multiple generations running concurrently
        self.players = players
        self.glitch_triforce = False
        self.algorithm = 'balanced'
        self.dungeons: Dict[Tuple[str, int], Dungeon] = {}
        self.regions = []
        self.shops = []
        self.itempool = []
        self.seed = None
        self.seed_name: str = "Unavailable"
        self.precollected_items = {player: [] for player in self.player_ids}
        self.state = CollectionState(self)
        self._cached_entrances = None
        self._cached_locations = None
        self._entrance_cache = {}
        self._location_cache = {}
        self.required_locations = []
        self.light_world_light_cone = False
        self.dark_world_light_cone = False
        self.rupoor_cost = 10
        self.aga_randomness = True
        self.lock_aga_door_in_escape = False
        self.save_and_quit_from_boss = True
        self.custom = False
        self.customitemarray = []
        self.shuffle_ganon = True
        self.dynamic_regions = []
        self.dynamic_locations = []
        self.spoiler = Spoiler(self)
        self.fix_trock_doors = self.AttributeProxy(
            lambda player: self.shuffle[player] != 'vanilla' or self.mode[player] == 'inverted')
        self.fix_skullwoods_exit = self.AttributeProxy(
            lambda player: self.shuffle[player] not in ['vanilla', 'simple', 'restricted', 'dungeonssimple'])
        self.fix_palaceofdarkness_exit = self.AttributeProxy(
            lambda player: self.shuffle[player] not in ['vanilla', 'simple', 'restricted', 'dungeonssimple'])
        self.fix_trock_exit = self.AttributeProxy(
            lambda player: self.shuffle[player] not in ['vanilla', 'simple', 'restricted', 'dungeonssimple'])
        self.NOTCURSED = self.AttributeProxy(lambda player: not self.CURSED[player])

        for player in range(1, players + 1):
            def set_player_attr(attr, val):
                self.__dict__.setdefault(attr, {})[player] = val

            set_player_attr('tech_tree_layout_prerequisites', {})
            set_player_attr('_region_cache', {})
            set_player_attr('shuffle', "vanilla")
            set_player_attr('logic', "noglitches")
            set_player_attr('mode', 'open')
            set_player_attr('difficulty', 'normal')
            set_player_attr('item_functionality', 'normal')
            set_player_attr('timer', False)
            set_player_attr('goal', 'ganon')
            set_player_attr('required_medallions', ['Ether', 'Quake'])
            set_player_attr('swamp_patch_required', False)
            set_player_attr('powder_patch_required', False)
            set_player_attr('ganon_at_pyramid', True)
            set_player_attr('ganonstower_vanilla', True)
            set_player_attr('can_access_trock_eyebridge', None)
            set_player_attr('can_access_trock_front', None)
            set_player_attr('can_access_trock_big_chest', None)
            set_player_attr('can_access_trock_middle', None)
            set_player_attr('fix_fake_world', True)
            set_player_attr('difficulty_requirements', None)
            set_player_attr('boss_shuffle', 'none')
            set_player_attr('enemy_health', 'default')
            set_player_attr('enemy_damage', 'default')
            set_player_attr('beemizer_total_chance', 0)
            set_player_attr('beemizer_trap_chance', 0)
            set_player_attr('escape_assist', [])
            set_player_attr('open_pyramid', False)
            set_player_attr('treasure_hunt_icon', 'Triforce Piece')
            set_player_attr('treasure_hunt_count', 0)
            set_player_attr('clock_mode', False)
            set_player_attr('countdown_start_time', 10)
            set_player_attr('red_clock_time', -2)
            set_player_attr('blue_clock_time', 2)
            set_player_attr('green_clock_time', 4)
            set_player_attr('can_take_damage', True)
            set_player_attr('triforce_pieces_available', 30)
            set_player_attr('triforce_pieces_required', 20)
            set_player_attr('shop_shuffle', 'off')
            set_player_attr('shuffle_prizes', "g")
            set_player_attr('sprite_pool', [])
            set_player_attr('dark_room_logic', "lamp")
            set_player_attr('plando_items', [])
            set_player_attr('plando_texts', {})
            set_player_attr('plando_connections', [])
            set_player_attr('game', "A Link to the Past")
            set_player_attr('completion_condition', lambda state: True)
        self.custom_data = {}
        self.worlds = {}
        self.slot_seeds = {}

    def set_seed(self, seed: Optional[int] = None, secure: bool = False, name: Optional[str] = None):
        self.seed = get_seed(seed)
        if secure:
            self.secure()
        else:
            self.random.seed(self.seed)
        self.seed_name = name if name else str(self.seed)
        self.slot_seeds = {player: random.Random(self.random.getrandbits(64)) for player in
                           range(1, self.players + 1)}

    def set_options(self, args):
        from worlds import AutoWorld
        for player in self.player_ids:
            self.custom_data[player] = {}
            world_type = AutoWorld.AutoWorldRegister.world_types[self.game[player]]
            for option_key in world_type.options:
                setattr(self, option_key, getattr(args, option_key, {}))
            for option_key in Options.common_options:
                setattr(self, option_key, getattr(args, option_key, {}))
            for option_key in Options.per_game_common_options:
                setattr(self, option_key, getattr(args, option_key, {}))
            self.worlds[player] = world_type(self, player)

    # intended for unittests
    def set_default_common_options(self):
        for option_key, option in Options.common_options.items():
            setattr(self, option_key, {player_id: option(option.default) for player_id in self.player_ids})
        for option_key, option in Options.per_game_common_options.items():
            setattr(self, option_key, {player_id: option(option.default) for player_id in self.player_ids})

    def secure(self):
        self.random = secrets.SystemRandom()
        self.is_race = True

    @functools.cached_property
    def player_ids(self):
        return tuple(range(1, self.players + 1))

    @functools.lru_cache()
    def get_game_players(self, game_name: str):
        return tuple(player for player in self.player_ids if self.game[player] == game_name)

    @functools.lru_cache()
    def get_game_worlds(self, game_name: str):
        return tuple(world for player, world in self.worlds.items() if self.game[player] == game_name)

    def get_name_string_for_object(self, obj) -> str:
        return obj.name if self.players == 1 else f'{obj.name} ({self.get_player_name(obj.player)})'

    def get_player_name(self, player: int) -> str:
        return self.player_name[player]

    def initialize_regions(self, regions=None):
        for region in regions if regions else self.regions:
            region.world = self
            self._region_cache[region.player][region.name] = region

    @functools.cached_property
    def world_name_lookup(self):
        return {self.player_name[player_id]: player_id for player_id in self.player_ids}

    def _recache(self):
        """Rebuild world cache"""
        for region in self.regions:
            player = region.player
            self._region_cache[player][region.name] = region
            for exit in region.exits:
                self._entrance_cache[exit.name, player] = exit

            for r_location in region.locations:
                self._location_cache[r_location.name, player] = r_location

    def get_regions(self, player=None):
        return self.regions if player is None else self._region_cache[player].values()

    def get_region(self, regionname: str, player: int) -> Region:
        try:
            return self._region_cache[player][regionname]
        except KeyError:
            self._recache()
            return self._region_cache[player][regionname]

    def get_entrance(self, entrance: str, player: int) -> Entrance:
        try:
            return self._entrance_cache[entrance, player]
        except KeyError:
            self._recache()
            return self._entrance_cache[entrance, player]

    def get_location(self, location: str, player: int) -> Location:
        try:
            return self._location_cache[location, player]
        except KeyError:
            self._recache()
            return self._location_cache[location, player]

    def get_dungeon(self, dungeonname: str, player: int) -> Dungeon:
        try:
            return self.dungeons[dungeonname, player]
        except KeyError as e:
            raise KeyError('No such dungeon %s for player %d' % (dungeonname, player)) from e

    def get_all_state(self, use_cache: bool) -> CollectionState:
        cached = getattr(self, "_all_state", None)
        if use_cache and cached:
            return cached.copy()

        ret = CollectionState(self)

        for item in self.itempool:
            self.worlds[item.player].collect(ret, item)
        from worlds.alttp.Dungeons import get_dungeon_item_pool
        for item in get_dungeon_item_pool(self):
            subworld = self.worlds[item.player]
            if item.name in subworld.dungeon_local_item_names:
                subworld.collect(ret, item)
        ret.sweep_for_events()

        if use_cache:
            self._all_state = ret
        return ret

    def get_items(self) -> list:
        return [loc.item for loc in self.get_filled_locations()] + self.itempool

    def find_item_locations(self, item, player: int) -> List[Location]:
        return [location for location in self.get_locations() if
                location.item and location.item.name == item and location.item.player == player]

    def find_item(self, item, player: int) -> Location:
        return next(location for location in self.get_locations() if
                    location.item and location.item.name == item and location.item.player == player)

    def find_items_in_locations(self, items: Set[str], player: int) -> List[Location]:
        return [location for location in self.get_locations() if
                location.item and location.item.name in items and location.item.player == player]

    def create_item(self, item_name: str, player: int) -> Item:
        return self.worlds[player].create_item(item_name)

    def push_precollected(self, item: Item):
        item.world = self
        self.precollected_items[item.player].append(item)
        self.state.collect(item, True)

    def push_item(self, location: Location, item: Item, collect: bool = True):
        if not isinstance(location, Location):
            raise RuntimeError(
                'Cannot assign item %s to invalid location %s (player %d).' % (item, location, item.player))

        if location.can_fill(self.state, item, False):
            location.item = item
            item.location = location
            item.world = self  # try to not have this here anymore
            if collect:
                self.state.collect(item, location.event, location)

            logging.debug('Placed %s at %s', item, location)
        else:
            raise RuntimeError('Cannot assign item %s to location %s.' % (item, location))

    def get_entrances(self) -> List[Entrance]:
        if self._cached_entrances is None:
            self._cached_entrances = [entrance for region in self.regions for entrance in region.entrances]
        return self._cached_entrances

    def clear_entrance_cache(self):
        self._cached_entrances = None

    def get_locations(self) -> List[Location]:
        if self._cached_locations is None:
            self._cached_locations = [location for region in self.regions for location in region.locations]
        return self._cached_locations

    def clear_location_cache(self):
        self._cached_locations = None

    def get_unfilled_locations(self, player=None) -> List[Location]:
        if player is not None:
            return [location for location in self.get_locations() if
                    location.player == player and not location.item]
        return [location for location in self.get_locations() if not location.item]

    def get_unfilled_dungeon_locations(self):
        return [location for location in self.get_locations() if not location.item and location.parent_region.dungeon]

    def get_filled_locations(self, player=None) -> List[Location]:
        if player is not None:
            return [location for location in self.get_locations() if
                    location.player == player and location.item is not None]
        return [location for location in self.get_locations() if location.item is not None]

    def get_reachable_locations(self, state=None, player=None) -> List[Location]:
        if state is None:
            state = self.state
        return [location for location in self.get_locations() if
                (player is None or location.player == player) and location.can_reach(state)]

    def get_placeable_locations(self, state=None, player=None) -> List[Location]:
        if state is None:
            state = self.state
        return [location for location in self.get_locations() if
                (player is None or location.player == player) and location.item is None and location.can_reach(state)]

    def get_unfilled_locations_for_players(self, locations, players: Iterable[int]):
        for player in players:
            if len(locations) == 0:
                locations = [location.name for location in self.get_unfilled_locations(player)]
            for location_name in locations:
                location = self._location_cache.get((location_name, player), None)
                if location is not None and location.item is None:
                    yield location

    def unlocks_new_location(self, item) -> bool:
        temp_state = self.state.copy()
        temp_state.collect(item, True)

        for location in self.get_unfilled_locations():
            if temp_state.can_reach(location) and not self.state.can_reach(location):
                return True

        return False

    def has_beaten_game(self, state, player: Optional[int] = None):
        if player:
            return self.completion_condition[player](state)
        else:
            return all((self.has_beaten_game(state, p) for p in range(1, self.players + 1)))

    def can_beat_game(self, starting_state: Optional[CollectionState] = None):
        if starting_state:
            if self.has_beaten_game(starting_state):
                return True
            state = starting_state.copy()
        else:
            if self.has_beaten_game(self.state):
                return True
            state = CollectionState(self)
        prog_locations = {location for location in self.get_locations() if location.item
                          and location.item.advancement and location not in state.locations_checked}

        while prog_locations:
            sphere = set()
            # build up spheres of collection radius.
            # Everything in each sphere is independent from each other in dependencies and only depends on lower spheres
            for location in prog_locations:
                if location.can_reach(state):
                    sphere.add(location)

            if not sphere:
                # ran out of places and did not finish yet, quit
                return False

            for location in sphere:
                state.collect(location.item, True, location)
            prog_locations -= sphere

            if self.has_beaten_game(state):
                return True

        return False

    def get_spheres(self):
        state = CollectionState(self)
        locations = set(self.get_filled_locations())

        while locations:
            sphere = set()

            for location in locations:
                if location.can_reach(state):
                    sphere.add(location)
            yield sphere
            if not sphere:
                if locations:
                    yield locations  # unreachable locations
                break

            for location in sphere:
                state.collect(location.item, True, location)
            locations -= sphere

    def fulfills_accessibility(self, state: Optional[CollectionState] = None):
        """Check if accessibility rules are fulfilled with current or supplied state."""
        if not state:
            state = CollectionState(self)
        players = {"minimal": set(),
                   "items": set(),
                   "locations": set()}
        for player, access in self.accessibility.items():
            players[access.current_key].add(player)

        beatable_fulfilled = False

        def location_conditition(location: Location):
            """Determine if this location has to be accessible, location is already filtered by location_relevant"""
            if location.player in players["minimal"]:
                return False
            return True

        def location_relevant(location: Location):
            """Determine if this location is relevant to sweep."""
            if location.player in players["locations"] or location.event or \
                    (location.item and location.item.advancement):
                return True
            return False

        def all_done():
            """Check if all access rules are fulfilled"""
            if beatable_fulfilled:
                if any(location_conditition(location) for location in locations):
                    return False  # still locations required to be collected
                return True

        locations = {location for location in self.get_locations() if location_relevant(location)}

        while locations:
            sphere = set()
            for location in locations:
                if location.can_reach(state):
                    sphere.add(location)

            if not sphere:
                # ran out of places and did not finish yet, quit
                logging.warning(f"Could not access required locations for accessibility check."
                                f" Missing: {locations}")
                return False

            for location in sphere:
                locations.remove(location)
                state.collect(location.item, True, location)

            if self.has_beaten_game(state):
                beatable_fulfilled = True

            if all_done():
                return True

        return False


class CollectionState(object):

    def __init__(self, parent: MultiWorld):
        self.prog_items = Counter()
        self.world = parent
        self.reachable_regions = {player: set() for player in range(1, parent.players + 1)}
        self.blocked_connections = {player: set() for player in range(1, parent.players + 1)}
        self.events = set()
        self.path = {}
        self.locations_checked = set()
        self.stale = {player: True for player in range(1, parent.players + 1)}
        for items in parent.precollected_items.values():
            for item in items:
                self.collect(item, True)

    def update_reachable_regions(self, player: int):
        from worlds.alttp.EntranceShuffle import indirect_connections
        self.stale[player] = False
        rrp = self.reachable_regions[player]
        bc = self.blocked_connections[player]
        queue = deque(self.blocked_connections[player])
        start = self.world.get_region('Menu', player)

        # init on first call - this can't be done on construction since the regions don't exist yet
        if not start in rrp:
            rrp.add(start)
            bc.update(start.exits)
            queue.extend(start.exits)

        # run BFS on all connections, and keep track of those blocked by missing items
        while queue:
            connection = queue.popleft()
            new_region = connection.connected_region
            if new_region in rrp:
                bc.remove(connection)
            elif connection.can_reach(self):
                rrp.add(new_region)
                bc.remove(connection)
                bc.update(new_region.exits)
                queue.extend(new_region.exits)
                self.path[new_region] = (new_region.name, self.path.get(connection, None))

                # Retry connections if the new region can unblock them
                if new_region.name in indirect_connections:
                    new_entrance = self.world.get_entrance(indirect_connections[new_region.name], player)
                    if new_entrance in bc and new_entrance not in queue:
                        queue.append(new_entrance)

    def copy(self) -> CollectionState:
        ret = CollectionState(self.world)
        ret.prog_items = self.prog_items.copy()
        ret.reachable_regions = {player: copy.copy(self.reachable_regions[player]) for player in
                                 range(1, self.world.players + 1)}
        ret.blocked_connections = {player: copy.copy(self.blocked_connections[player]) for player in
                                   range(1, self.world.players + 1)}
        ret.events = copy.copy(self.events)
        ret.path = copy.copy(self.path)
        ret.locations_checked = copy.copy(self.locations_checked)
        return ret

    def can_reach(self, spot, resolution_hint=None, player=None) -> bool:
        if not hasattr(spot, "spot_type"):
            # try to resolve a name
            if resolution_hint == 'Location':
                spot = self.world.get_location(spot, player)
            elif resolution_hint == 'Entrance':
                spot = self.world.get_entrance(spot, player)
            else:
                # default to Region
                spot = self.world.get_region(spot, player)
        return spot.can_reach(self)

    def sweep_for_events(self, key_only: bool = False, locations=None):
        if locations is None:
            locations = self.world.get_filled_locations()
        new_locations = True
        # since the loop has a good chance to run more than once, only filter the events once
        locations = {location for location in locations if location.event}
        while new_locations:
            reachable_events = {location for location in locations if
                                (not key_only or getattr(location.item, "locked_dungeon_item", False))
                                and location.can_reach(self)}
            new_locations = reachable_events - self.events
            for event in new_locations:
                self.events.add(event)
                self.collect(event.item, True, event)

    def has(self, item, player: int, count: int = 1):
        return self.prog_items[item, player] >= count

    def has_all(self, items: Set[str], player: int):
        return all(self.prog_items[item, player] for item in items)

    def has_any(self, items: Set[str], player: int):
        return any(self.prog_items[item, player] for item in items)

    def has_group(self, item_name_group: str, player: int, count: int = 1):
        found: int = 0
        for item_name in self.world.worlds[player].item_name_groups[item_name_group]:
            found += self.prog_items[item_name, player]
            if found >= count:
                return True
        return False

    def count_group(self, item_name_group: str, player: int):
        found: int = 0
        for item_name in self.world.worlds[player].item_name_groups[item_name_group]:
            found += self.prog_items[item_name, player]
        return found

    def can_buy_unlimited(self, item: str, player: int) -> bool:
        return any(shop.region.player == player and shop.has_unlimited(item) and shop.region.can_reach(self) for
                   shop in self.world.shops)

    def can_buy(self, item: str, player: int) -> bool:
        return any(shop.region.player == player and shop.has(item) and shop.region.can_reach(self) for
                   shop in self.world.shops)

    def item_count(self, item: str, player: int) -> int:
        return self.prog_items[item, player]

    def has_triforce_pieces(self, count: int, player: int) -> bool:
        return self.item_count('Triforce Piece', player) + self.item_count('Power Star', player) >= count

    def has_crystals(self, count: int, player: int) -> bool:
        found: int = 0
        for crystalnumber in range(1, 8):
            found += self.prog_items[f"Crystal {crystalnumber}", player]
            if found >= count:
                return True
        return False

    def can_lift_rocks(self, player: int):
        return self.has('Power Glove', player) or self.has('Titans Mitts', player)

    def bottle_count(self, player: int) -> int:
        return min(self.world.difficulty_requirements[player].progressive_bottle_limit,
                   self.count_group("Bottles", player))

    def has_hearts(self, player: int, count: int) -> int:
        # Warning: This only considers items that are marked as advancement items
        return self.heart_count(player) >= count

    def heart_count(self, player: int) -> int:
        # Warning: This only considers items that are marked as advancement items
        diff = self.world.difficulty_requirements[player]
        return min(self.item_count('Boss Heart Container', player), diff.boss_heart_container_limit) \
               + self.item_count('Sanctuary Heart Container', player) \
               + min(self.item_count('Piece of Heart', player), diff.heart_piece_limit) // 4 \
               + 3  # starting hearts

    def can_lift_heavy_rocks(self, player: int) -> bool:
        return self.has('Titans Mitts', player)

    def can_extend_magic(self, player: int, smallmagic: int = 16,
                         fullrefill: bool = False):  # This reflects the total magic Link has, not the total extra he has.
        basemagic = 8
        if self.has('Magic Upgrade (1/4)', player):
            basemagic = 32
        elif self.has('Magic Upgrade (1/2)', player):
            basemagic = 16
        if self.can_buy_unlimited('Green Potion', player) or self.can_buy_unlimited('Blue Potion', player):
            if self.world.item_functionality[player] == 'hard' and not fullrefill:
                basemagic = basemagic + int(basemagic * 0.5 * self.bottle_count(player))
            elif self.world.item_functionality[player] == 'expert' and not fullrefill:
                basemagic = basemagic + int(basemagic * 0.25 * self.bottle_count(player))
            else:
                basemagic = basemagic + basemagic * self.bottle_count(player)
        return basemagic >= smallmagic

    def can_kill_most_things(self, player: int, enemies=5) -> bool:
        return (self.has_melee_weapon(player)
                or self.has('Cane of Somaria', player)
                or (self.has('Cane of Byrna', player) and (enemies < 6 or self.can_extend_magic(player)))
                or self.can_shoot_arrows(player)
                or self.has('Fire Rod', player)
                or (self.has('Bombs (10)', player) and enemies < 6))

    def can_shoot_arrows(self, player: int) -> bool:
        if self.world.retro[player]:
            return (self.has('Bow', player) or self.has('Silver Bow', player)) and self.can_buy('Single Arrow', player)
        return self.has('Bow', player) or self.has('Silver Bow', player)

    def can_get_good_bee(self, player: int) -> bool:
        cave = self.world.get_region('Good Bee Cave', player)
        return (
                self.has_group("Bottles", player) and
                self.has('Bug Catching Net', player) and
                (self.has('Pegasus Boots', player) or (self.has_sword(player) and self.has('Quake', player))) and
                cave.can_reach(self) and
                self.is_not_bunny(cave, player)
        )

    def can_retrieve_tablet(self, player: int) -> bool:
        return self.has('Book of Mudora', player) and (self.has_beam_sword(player) or
                                                       (self.world.swordless[player] and
                                                        self.has("Hammer", player)))

    def has_sword(self, player: int) -> bool:
        return self.has('Fighter Sword', player) \
               or self.has('Master Sword', player) \
               or self.has('Tempered Sword', player) \
               or self.has('Golden Sword', player)

    def has_beam_sword(self, player: int) -> bool:
        return self.has('Master Sword', player) or self.has('Tempered Sword', player) or self.has('Golden Sword',
                                                                                                  player)

    def has_melee_weapon(self, player: int) -> bool:
        return self.has_sword(player) or self.has('Hammer', player)

    def has_fire_source(self, player: int) -> bool:
        return self.has('Fire Rod', player) or self.has('Lamp', player)

    def can_melt_things(self, player: int) -> bool:
        return self.has('Fire Rod', player) or \
               (self.has('Bombos', player) and
                (self.world.swordless[player] or
                 self.has_sword(player)))

    def can_avoid_lasers(self, player: int) -> bool:
        return self.has('Mirror Shield', player) or self.has('Cane of Byrna', player) or self.has('Cape', player)

    def is_not_bunny(self, region: Region, player: int) -> bool:
        if self.has('Moon Pearl', player):
            return True

        return region.is_light_world if self.world.mode[player] != 'inverted' else region.is_dark_world

    def can_reach_light_world(self, player: int) -> bool:
        if True in [i.is_light_world for i in self.reachable_regions[player]]:
            return True
        return False

    def can_reach_dark_world(self, player: int) -> bool:
        if True in [i.is_dark_world for i in self.reachable_regions[player]]:
            return True
        return False

    def has_misery_mire_medallion(self, player: int) -> bool:
        return self.has(self.world.required_medallions[player][0], player)

    def has_turtle_rock_medallion(self, player: int) -> bool:
        return self.has(self.world.required_medallions[player][1], player)

    def can_boots_clip_lw(self, player: int):
        if self.world.mode[player] == 'inverted':
            return self.has('Pegasus Boots', player) and self.has('Moon Pearl', player)
        return self.has('Pegasus Boots', player)

    def can_boots_clip_dw(self, player: int):
        if self.world.mode[player] != 'inverted':
            return self.has('Pegasus Boots', player) and self.has('Moon Pearl', player)
        return self.has('Pegasus Boots', player)

    def can_get_glitched_speed_lw(self, player: int):
        rules = [self.has('Pegasus Boots', player), any([self.has('Hookshot', player), self.has_sword(player)])]
        if self.world.mode[player] == 'inverted':
            rules.append(self.has('Moon Pearl', player))
        return all(rules)

    def can_superbunny_mirror_with_sword(self, player: int):
        return self.has('Magic Mirror', player) and self.has_sword(player)

    def can_get_glitched_speed_dw(self, player: int):
        rules = [self.has('Pegasus Boots', player), any([self.has('Hookshot', player), self.has_sword(player)])]
        if self.world.mode[player] != 'inverted':
            rules.append(self.has('Moon Pearl', player))
        return all(rules)

    def can_bomb_clip(self, region: Region, player: int) -> bool:
        return self.is_not_bunny(region, player) and self.has('Pegasus Boots', player)

    def collect(self, item: Item, event: bool = False, location: Location = None) -> bool:
        if location:
            self.locations_checked.add(location)

        changed = self.world.worlds[item.player].collect(self, item)

        if not changed and event:
            self.prog_items[item.name, item.player] += 1
            changed = True

        self.stale[item.player] = True

        if changed and not event:
            self.sweep_for_events()

        return changed

    def remove(self, item: Item):
        changed = self.world.worlds[item.player].remove(self, item)
        if changed:
            # invalidate caches, nothing can be trusted anymore now
            self.reachable_regions[item.player] = set()
            self.blocked_connections[item.player] = set()
            self.stale[item.player] = True


@unique
class RegionType(int, Enum):
    Generic = 0
    LightWorld = 1
    DarkWorld = 2
    Cave = 3  # Also includes Houses
    Dungeon = 4

    @property
    def is_indoors(self) -> bool:
        """Shorthand for checking if Cave or Dungeon"""
        return self in (RegionType.Cave, RegionType.Dungeon)


class Region(object):
    def __init__(self, name: str, type_: RegionType, hint, player: int, world: Optional[MultiWorld] = None):
        self.name = name
        self.type = type_
        self.entrances = []
        self.exits = []
        self.locations: List[Location] = []
        self.dungeon = None
        self.shop = None
        self.world = world
        self.is_light_world = False  # will be set after making connections.
        self.is_dark_world = False
        self.spot_type = 'Region'
        self.hint_text = hint
        self.player = player

    def can_reach(self, state: CollectionState) -> bool:
        if state.stale[self.player]:
            state.update_reachable_regions(self.player)
        return self in state.reachable_regions[self.player]

    def can_reach_private(self, state: CollectionState) -> bool:
        for entrance in self.entrances:
            if entrance.can_reach(state):
                if not self in state.path:
                    state.path[self] = (self.name, state.path.get(entrance, None))
                return True
        return False

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return self.world.get_name_string_for_object(self) if self.world else f'{self.name} (Player {self.player})'


class Entrance(object):
    spot_type = 'Entrance'

    def __init__(self, player: int, name: str = '', parent=None):
        self.name = name
        self.parent_region = parent
        self.connected_region = None
        self.target = None
        self.addresses = None
        self.access_rule = lambda state: True
        self.player = player
        self.hide_path = False

    def can_reach(self, state: CollectionState) -> bool:
        if self.parent_region.can_reach(state) and self.access_rule(state):
            if not self.hide_path and not self in state.path:
                state.path[self] = (self.name, state.path.get(self.parent_region, (self.parent_region.name, None)))
            return True

        return False

    def connect(self, region: Region, addresses=None, target = None):
        self.connected_region = region
        self.target = target
        self.addresses = addresses
        region.entrances.append(self)

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        world = self.parent_region.world if self.parent_region else None
        return world.get_name_string_for_object(self) if world else f'{self.name} (Player {self.player})'


class Dungeon(object):
    def __init__(self, name: str, regions, big_key, small_keys, dungeon_items, player: int):
        self.name = name
        self.regions = regions
        self.big_key = big_key
        self.small_keys = small_keys
        self.dungeon_items = dungeon_items
        self.bosses = dict()
        self.player = player
        self.world = None

    @property
    def boss(self) -> Optional[Boss]:
        return self.bosses.get(None, None)

    @boss.setter
    def boss(self, value: Optional[Boss]):
        self.bosses[None] = value

    @property
    def keys(self):
        return self.small_keys + ([self.big_key] if self.big_key else [])

    @property
    def all_items(self):
        return self.dungeon_items + self.keys

    def is_dungeon_item(self, item: Item) -> bool:
        return item.player == self.player and item.name in (dungeon_item.name for dungeon_item in self.all_items)

    def __eq__(self, other: Dungeon) -> bool:
        if not other:
            return False
        return self.name == other.name and self.player == other.player

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return self.world.get_name_string_for_object(self) if self.world else f'{self.name} (Player {self.player})'


class Boss():
    def __init__(self, name: str, enemizer_name: str, defeat_rule, player: int):
        self.name = name
        self.enemizer_name = enemizer_name
        self.defeat_rule = defeat_rule
        self.player = player

    def can_defeat(self, state) -> bool:
        return self.defeat_rule(state, self.player)

    def __repr__(self):
        return f"Boss({self.name})"


class LocationProgressType(Enum):
    DEFAULT = 1
    PRIORITY = 2
    EXCLUDED = 3

class Location():
    # If given as integer, then this is the shop's inventory index
    shop_slot: Optional[int] = None
    shop_slot_disabled: bool = False
    event: bool = False
    locked: bool = False
    spot_type = 'Location'
    game: str = "Generic"
    show_in_spoiler: bool = True
    excluded: bool = False
    crystal: bool = False
    progress_type: LocationProgressType = LocationProgressType.DEFAULT
    always_allow = staticmethod(lambda item, state: False)
    access_rule = staticmethod(lambda state: True)
    item_rule = staticmethod(lambda item: True)

    def __init__(self, player: int, name: str = '', address: int = None, parent=None):
        self.name: str = name
        self.address: Optional[int] = address
        self.parent_region: Region = parent
        self.player: int = player
        self.item: Optional[Item] = None

    def can_fill(self, state: CollectionState, item: Item, check_access=True) -> bool:
        return self.always_allow(state, item) or (self.item_rule(item) and (not check_access or self.can_reach(state)))

    def can_reach(self, state: CollectionState) -> bool:
        # self.access_rule computes faster on average, so placing it first for faster abort
        if self.access_rule(state) and self.parent_region.can_reach(state):
            return True
        return False

    def place_locked_item(self, item: Item):
        if self.item:
            raise Exception(f"Location {self} already filled.")
        self.item = item
        self.event = item.advancement
        self.item.world = self.parent_region.world
        self.locked = True

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        world = self.parent_region.world if self.parent_region and self.parent_region.world else None
        return world.get_name_string_for_object(self) if world else f'{self.name} (Player {self.player})'

    def __hash__(self):
        return hash((self.name, self.player))

    def __lt__(self, other):
        return (self.player, self.name) < (other.player, other.name)

    @property
    def native_item(self) -> bool:
        """Returns True if the item in this location matches game."""
        return self.item and self.item.game == self.game

    @property
    def hint_text(self):
        hint_text = getattr(self, "_hint_text", None)
        if hint_text:
            return hint_text
        return "at " + self.name.replace("_", " ").replace("-", " ")


class Item():
    location: Optional[Location] = None
    world: Optional[MultiWorld] = None
    code: Optional[int] = None  # an item with ID None is called an Event, and does not get written to multidata
    name: str
    game: str = "Generic"
    type: str = None
    # indicates if this is a negative impact item. Causes these to be handled differently by various games.
    trap: bool = False
    # change manually to ensure that a specific non-progression item never goes on an excluded location
    never_exclude = False

    # need to find a decent place for these to live and to allow other games to register texts if they want.
    pedestal_credit_text: str = "and the Unknown Item"
    sickkid_credit_text: Optional[str] = None
    magicshop_credit_text: Optional[str] = None
    zora_credit_text: Optional[str] = None
    fluteboy_credit_text: Optional[str] = None

    # hopefully temporary attributes to satisfy legacy LttP code, proper implementation in subclass ALttPItem
    smallkey: bool = False
    bigkey: bool = False
    map: bool = False
    compass: bool = False

    def __init__(self, name: str, advancement: bool, code: Optional[int], player: int):
        self.name = name
        self.advancement = advancement
        self.player = player
        self.code = code

    @property
    def hint_text(self):
        return getattr(self, "_hint_text", self.name.replace("_", " ").replace("-", " "))

    @property
    def pedestal_hint_text(self):
        return getattr(self, "_pedestal_hint_text", self.name.replace("_", " ").replace("-", " "))

    @property
    def flags(self) -> int:
        return self.advancement + (self.never_exclude << 1) + (self.trap << 2)

    def __eq__(self, other):
        return self.name == other.name and self.player == other.player

    def __lt__(self, other):
        if other.player != self.player:
            return other.player < self.player
        return self.name < other.name

    def __hash__(self):
        return hash((self.name, self.player))

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return self.world.get_name_string_for_object(self) if self.world else f'{self.name} (Player {self.player})'


class Spoiler():
    world: MultiWorld

    def __init__(self, world):
        self.world = world
        self.hashes = {}
        self.entrances = OrderedDict()
        self.medallions = {}
        self.playthrough = {}
        self.unreachables = []
        self.locations = {}
        self.paths = {}
        self.shops = []
        self.bosses = OrderedDict()

    def set_entrance(self, entrance, exit, direction, player):
        if self.world.players == 1:
            self.entrances[(entrance, direction, player)] = OrderedDict(
                [('entrance', entrance), ('exit', exit), ('direction', direction)])
        else:
            self.entrances[(entrance, direction, player)] = OrderedDict(
                [('player', player), ('entrance', entrance), ('exit', exit), ('direction', direction)])

    def parse_data(self):
        self.medallions = OrderedDict()
        for player in self.world.get_game_players("A Link to the Past"):
            self.medallions[f'Misery Mire ({self.world.get_player_name(player)})'] = \
                self.world.required_medallions[player][0]
            self.medallions[f'Turtle Rock ({self.world.get_player_name(player)})'] = \
                self.world.required_medallions[player][1]

        self.locations = OrderedDict()
        listed_locations = set()

        lw_locations = [loc for loc in self.world.get_locations() if
                        loc not in listed_locations and loc.parent_region and loc.parent_region.type == RegionType.LightWorld and loc.show_in_spoiler]
        self.locations['Light World'] = OrderedDict(
            [(str(location), str(location.item) if location.item is not None else 'Nothing') for location in
             lw_locations])
        listed_locations.update(lw_locations)

        dw_locations = [loc for loc in self.world.get_locations() if
                        loc not in listed_locations and loc.parent_region and loc.parent_region.type == RegionType.DarkWorld and loc.show_in_spoiler]
        self.locations['Dark World'] = OrderedDict(
            [(str(location), str(location.item) if location.item is not None else 'Nothing') for location in
             dw_locations])
        listed_locations.update(dw_locations)

        cave_locations = [loc for loc in self.world.get_locations() if
                          loc not in listed_locations and loc.parent_region and loc.parent_region.type == RegionType.Cave and loc.show_in_spoiler]
        self.locations['Caves'] = OrderedDict(
            [(str(location), str(location.item) if location.item is not None else 'Nothing') for location in
             cave_locations])
        listed_locations.update(cave_locations)

        for dungeon in self.world.dungeons.values():
            dungeon_locations = [loc for loc in self.world.get_locations() if
                                 loc not in listed_locations and loc.parent_region and loc.parent_region.dungeon == dungeon and loc.show_in_spoiler]
            self.locations[str(dungeon)] = OrderedDict(
                [(str(location), str(location.item) if location.item is not None else 'Nothing') for location in
                 dungeon_locations])
            listed_locations.update(dungeon_locations)

        other_locations = [loc for loc in self.world.get_locations() if
                           loc not in listed_locations and loc.show_in_spoiler]
        if other_locations:
            self.locations['Other Locations'] = OrderedDict(
                [(str(location), str(location.item) if location.item is not None else 'Nothing') for location in
                 other_locations])
            listed_locations.update(other_locations)

        self.shops = []
        from worlds.alttp.Shops import ShopType, price_type_display_name, price_rate_display
        for shop in self.world.shops:
            if not shop.custom:
                continue
            shopdata = {
                'location': str(shop.region),
                'type': 'Take Any' if shop.type == ShopType.TakeAny else 'Shop'
            }
            for index, item in enumerate(shop.inventory):
                if item is None:
                    continue
                my_price = item['price'] // price_rate_display.get(item['price_type'], 1)
                shopdata['item_{}'.format(
                    index)] = f"{item['item']} — {my_price} {price_type_display_name[item['price_type']]}"

                if item['player'] > 0:
                    shopdata['item_{}'.format(index)] = shopdata['item_{}'.format(index)].replace('—',
                                                                                                  '(Player {}) — '.format(
                                                                                                      item['player']))

                if item['max'] == 0:
                    continue
                shopdata['item_{}'.format(index)] += " x {}".format(item['max'])

                if item['replacement'] is None:
                    continue
                shopdata['item_{}'.format(
                    index)] += f", {item['replacement']} - {item['replacement_price']} {price_type_display_name[item['replacement_price_type']]}"
            self.shops.append(shopdata)

        for player in self.world.get_game_players("A Link to the Past"):
            self.bosses[str(player)] = OrderedDict()
            self.bosses[str(player)]["Eastern Palace"] = self.world.get_dungeon("Eastern Palace", player).boss.name
            self.bosses[str(player)]["Desert Palace"] = self.world.get_dungeon("Desert Palace", player).boss.name
            self.bosses[str(player)]["Tower Of Hera"] = self.world.get_dungeon("Tower of Hera", player).boss.name
            self.bosses[str(player)]["Hyrule Castle"] = "Agahnim"
            self.bosses[str(player)]["Palace Of Darkness"] = self.world.get_dungeon("Palace of Darkness",
                                                                                    player).boss.name
            self.bosses[str(player)]["Swamp Palace"] = self.world.get_dungeon("Swamp Palace", player).boss.name
            self.bosses[str(player)]["Skull Woods"] = self.world.get_dungeon("Skull Woods", player).boss.name
            self.bosses[str(player)]["Thieves Town"] = self.world.get_dungeon("Thieves Town", player).boss.name
            self.bosses[str(player)]["Ice Palace"] = self.world.get_dungeon("Ice Palace", player).boss.name
            self.bosses[str(player)]["Misery Mire"] = self.world.get_dungeon("Misery Mire", player).boss.name
            self.bosses[str(player)]["Turtle Rock"] = self.world.get_dungeon("Turtle Rock", player).boss.name
            if self.world.mode[player] != 'inverted':
                self.bosses[str(player)]["Ganons Tower Basement"] = \
                    self.world.get_dungeon('Ganons Tower', player).bosses['bottom'].name
                self.bosses[str(player)]["Ganons Tower Middle"] = self.world.get_dungeon('Ganons Tower', player).bosses[
                    'middle'].name
                self.bosses[str(player)]["Ganons Tower Top"] = self.world.get_dungeon('Ganons Tower', player).bosses[
                    'top'].name
            else:
                self.bosses[str(player)]["Ganons Tower Basement"] = \
                    self.world.get_dungeon('Inverted Ganons Tower', player).bosses['bottom'].name
                self.bosses[str(player)]["Ganons Tower Middle"] = \
                    self.world.get_dungeon('Inverted Ganons Tower', player).bosses['middle'].name
                self.bosses[str(player)]["Ganons Tower Top"] = \
                    self.world.get_dungeon('Inverted Ganons Tower', player).bosses['top'].name

            self.bosses[str(player)]["Ganons Tower"] = "Agahnim 2"
            self.bosses[str(player)]["Ganon"] = "Ganon"

    def to_json(self):
        self.parse_data()
        out = OrderedDict()
        out['Entrances'] = list(self.entrances.values())
        out.update(self.locations)
        out['Special'] = self.medallions
        if self.hashes:
            out['Hashes'] = self.hashes
        if self.shops:
            out['Shops'] = self.shops
        out['playthrough'] = self.playthrough
        out['paths'] = self.paths
        out['Bosses'] = self.bosses

        return json.dumps(out)

    def to_file(self, filename):
        from worlds.AutoWorld import call_all, call_single, call_stage
        self.parse_data()

        def bool_to_text(variable: Union[bool, str]) -> str:
            if type(variable) == str:
                return variable
            return 'Yes' if variable else 'No'

        def write_option(option_key: str, option_obj: type(Options.Option)):
            res = getattr(self.world, option_key)[player]
            displayname = getattr(option_obj, "displayname", option_key)
            try:
                outfile.write(f'{displayname + ":":33}{res.get_current_option_name()}\n')
            except:
                raise Exception

        with open(filename, 'w', encoding="utf-8-sig") as outfile:
            outfile.write(
                'Archipelago Version %s  -  Seed: %s\n\n' % (
                    Utils.__version__, self.world.seed))
            outfile.write('Filling Algorithm:               %s\n' % self.world.algorithm)
            outfile.write('Players:                         %d\n' % self.world.players)
            call_stage(self.world, "write_spoiler_header", outfile)

            for player in range(1, self.world.players + 1):
                if self.world.players > 1:
                    outfile.write('\nPlayer %d: %s\n' % (player, self.world.get_player_name(player)))
                outfile.write('Game:                            %s\n' % self.world.game[player])
                for f_option, option in Options.per_game_common_options.items():
                    write_option(f_option, option)
                options = self.world.worlds[player].options
                if options:
                    for f_option, option in options.items():
                        write_option(f_option, option)
                call_single(self.world, "write_spoiler_header", player, outfile)

                if player in self.world.get_game_players("A Link to the Past"):
                    outfile.write('%s%s\n' % ('Hash: ', self.hashes[player]))

                    outfile.write('Logic:                           %s\n' % self.world.logic[player])
                    outfile.write('Dark Room Logic:                 %s\n' % self.world.dark_room_logic[player])
                    outfile.write('Mode:                            %s\n' % self.world.mode[player])
                    outfile.write('Goal:                            %s\n' % self.world.goal[player])
                    if "triforce" in self.world.goal[player]:  # triforce hunt
                        outfile.write("Pieces available for Triforce:   %s\n" %
                                      self.world.triforce_pieces_available[player])
                        outfile.write("Pieces required for Triforce:    %s\n" %
                                      self.world.triforce_pieces_required[player])
                    outfile.write('Difficulty:                      %s\n' % self.world.difficulty[player])
                    outfile.write('Item Functionality:              %s\n' % self.world.item_functionality[player])
                    outfile.write('Entrance Shuffle:                %s\n' % self.world.shuffle[player])
                    if self.world.shuffle[player] != "vanilla":
                        outfile.write('Entrance Shuffle Seed            %s\n' % self.world.worlds[player].er_seed)
                    outfile.write('Pyramid hole pre-opened:         %s\n' % (
                        'Yes' if self.world.open_pyramid[player] else 'No'))
                    outfile.write('Shop inventory shuffle:          %s\n' %
                                  bool_to_text("i" in self.world.shop_shuffle[player]))
                    outfile.write('Shop price shuffle:              %s\n' %
                                  bool_to_text("p" in self.world.shop_shuffle[player]))
                    outfile.write('Shop upgrade shuffle:            %s\n' %
                                  bool_to_text("u" in self.world.shop_shuffle[player]))
                    outfile.write('New Shop inventory:              %s\n' %
                                  bool_to_text("g" in self.world.shop_shuffle[player] or
                                               "f" in self.world.shop_shuffle[player]))
                    outfile.write('Custom Potion Shop:              %s\n' %
                                  bool_to_text("w" in self.world.shop_shuffle[player]))
                    outfile.write('Boss shuffle:                    %s\n' % self.world.boss_shuffle[player])
                    outfile.write('Enemy health:                    %s\n' % self.world.enemy_health[player])
                    outfile.write('Enemy damage:                    %s\n' % self.world.enemy_damage[player])
                    outfile.write('Prize shuffle                    %s\n' %
                                  self.world.shuffle_prizes[player])
            if self.entrances:
                outfile.write('\n\nEntrances:\n\n')
                outfile.write('\n'.join(['%s%s %s %s' % (f'{self.world.get_player_name(entry["player"])}: '
                                                         if self.world.players > 1 else '', entry['entrance'],
                                                         '<=>' if entry['direction'] == 'both' else
                                                         '<=' if entry['direction'] == 'exit' else '=>',
                                                         entry['exit']) for entry in self.entrances.values()]))

            if self.medallions:
                outfile.write('\n\nMedallions:\n')
                for dungeon, medallion in self.medallions.items():
                    outfile.write(f'\n{dungeon}: {medallion}')

            call_all(self.world, "write_spoiler", outfile)

            outfile.write('\n\nLocations:\n\n')
            outfile.write('\n'.join(
                ['%s: %s' % (location, item) for grouping in self.locations.values() for (location, item) in
                 grouping.items()]))

            if self.shops:
                outfile.write('\n\nShops:\n\n')
                outfile.write('\n'.join("{} [{}]\n    {}".format(shop['location'], shop['type'], "\n    ".join(
                    item for item in [shop.get('item_0', None), shop.get('item_1', None), shop.get('item_2', None)] if
                    item)) for shop in self.shops))

            for player in self.world.get_game_players("A Link to the Past"):
                if self.world.boss_shuffle[player] != 'none':
                    bossmap = self.bosses[str(player)] if self.world.players > 1 else self.bosses
                    outfile.write(
                        f'\n\nBosses{(f" ({self.world.get_player_name(player)})" if self.world.players > 1 else "")}:\n')
                    outfile.write('    ' + '\n    '.join([f'{x}: {y}' for x, y in bossmap.items()]))
            outfile.write('\n\nPlaythrough:\n\n')
            outfile.write('\n'.join(['%s: {\n%s\n}' % (sphere_nr, '\n'.join(
                ['  %s: %s' % (location, item) for (location, item) in sphere.items()] if sphere_nr != '0' else [
                    f'  {item}' for item in sphere])) for (sphere_nr, sphere) in self.playthrough.items()]))
            if self.unreachables:
                outfile.write('\n\nUnreachable Items:\n\n')
                outfile.write(
                    '\n'.join(['%s: %s' % (unreachable.item, unreachable) for unreachable in self.unreachables]))

            if self.paths:
                outfile.write('\n\nPaths:\n\n')
                path_listings = []
                for location, path in sorted(self.paths.items()):
                    path_lines = []
                    for region, exit in path:
                        if exit is not None:
                            path_lines.append("{} -> {}".format(region, exit))
                        else:
                            path_lines.append(region)
                    path_listings.append("{}\n        {}".format(location, "\n   =>   ".join(path_lines)))

                outfile.write('\n'.join(path_listings))
            call_all(self.world, "write_spoiler_end", outfile)


seeddigits = 20


def get_seed(seed=None):
    if seed is None:
        random.seed(None)
        return random.randint(0, pow(10, seeddigits) - 1)
    return seed
