import gdb
import re

# Required to make calls to super () work in python2.
__metaclass__ = type

#=====================================================================#

# Should debug messages be printed?
DEFAULT_DEBUG = False

# The default maximum group size.
DEFAULT_MAX_GROUP_SIZE = 4096

# The default size for the "pages" in the ComRV cache and storage area.
DEFAULT_MIN_COMRV_CACHE_ENTRY_SIZE_IN_BYTES = 512
OVERLAY_MIN_CACHE_ENTRY_SIZE_IN_BYTES = 512

# Various symbols that are read in order to parse ComRV.
INIT_SYMBOL = "g_stComrvCB.ucTablesLoaded"
MULTI_GROUP_OFFSET_SYMBOL = "g_stComrvCB.ucMultiGroupOffset"
OVERLAY_STORAGE_START_SYMBOL = "OVERLAY_START_OF_OVERLAYS"
OVERLAY_STORAGE_END_SYMBOL = "OVERLAY_END_OF_OVERLAYS"
OVERLAY_CACHE_START_SYMBOL = "__OVERLAY_CACHE_START__"
OVERLAY_CACHE_END_SYMBOL = "__OVERLAY_CACHE_END__"
COMRV_RETURN_FROM_CALLEE_LABEL = "comrv_ret_from_callee"

# The following symbols are actually used as format strings.  They must
# include a single '%d' format specified which is replaced with the ComRV
# cache index.
OVERLAY_CACHE_AT_INDEX_TO_GROUP_ID \
    = "g_stComrvCB.stOverlayCache[%d].unToken.stFields.uiOverlayGroupID"
OVERLAY_CACHE_AT_INDEX_TO_SIZE_IN_MIN_UNITS \
    = "g_stComrvCB.stOverlayCache[%d].unProperties.stFields.ucSizeInMinGroupSizeUnits"

#=====================================================================#

# A class for the control variable 'set/show debug comrv on|off'.
class debug_parameter (gdb.Parameter):
    '''Controls debugging messages from the Python Overlay Manager.  This
should only be needed to help track down bugs in the Python code.'''
    set_doc = "Set whether debugging from the Python Overlay Manager is on."
    show_doc = "Show whether debugging from the Python Overlay Manager is on."
    def __init__ (self):
        gdb.Parameter.__init__ (self, "debug comrv",
                                gdb.COMMAND_MAINTENANCE,
                                gdb.PARAM_BOOLEAN)
        self.value = DEFAULT_DEBUG

    def get_show_string (self, value):
        return ("Debugging of ComRV Python overlay manager is %s."
                % (value))

    def __nonzero__ (self):
        if (self.value):
            return 1
        else:
            return 0

    def __bool__ (self):
        return self.value

# An instance of the debug parameter.  Due to operator overloading
# this can be treated as a boolean like:
#   if (overlay_debug):
#     ...
overlay_debug = debug_parameter ()

# Class to create the 'set comrv' prefix command.
class set_comrv_prefix_command (gdb.Command):
    def __init__ (self):
        gdb.Command.__init__ (self, "set comrv", gdb.COMMAND_NONE, gdb.COMPLETE_NONE, True)

# Class to create the 'show comrv' prefix command.
class show_comrv_prefix_command (gdb.Command):
    def __init__ (self):
        gdb.Command.__init__ (self, "show comrv", gdb.COMMAND_NONE, gdb.COMPLETE_NONE, True)

# Now instantiate the above classes, actually creating the 'set comrv' and
# 'show comrv' prefix commands.
set_comrv_prefix_command ()
show_comrv_prefix_command ()

# Class that represents the maximum overlay group size.  This is used when
# unwinding the ComRV stack.
class max_group_size_parameter (gdb.Parameter):
    '''The maximum group size.  This is a hard coded constant within the
toolchain and ComRV.  The value here must be adjusted to match.  This value
is required in order to correctly unwind the ComRV stack.

Changing this once GDB has already parsed the ComRV data structures will
cause undefined behaviour.  This should only be modified once, immediately
after initially loading the ComRV support Pythong script.'''
    set_doc = "Set the maximum overlay group size."
    show_doc = "Show the maximum overlay group size."
    def __init__ (self):
        gdb.Parameter.__init__ (self, "comrv max-group-size",
                                gdb.COMMAND_STACK,
                                gdb.PARAM_ZUINTEGER)
        self.value = DEFAULT_MAX_GROUP_SIZE

    def get_show_string (self, value):
        return ("Maximum ComRV overlay group size is %s." % (value))

# Instance of parameter object.  Use the value field of this object.
max_group_size = max_group_size_parameter ()

# Class that represents the size of the "pages" in the ComRV cache and
# storage area.  This is the minimum unit size in which overlays are
# measured.
class min_overlay_entry_size_parameter (gdb.Parameter):
    '''The minimum size for a ComRV overlay.  Many aspects of Comrv are
measured in multiples of this minimum size.  This value must match the
value used by the compiler, linker, and ComRV enginee.

Changing this once GDB has already parsed the ComRV data structures will
cause undefined behaviour.  This should only be modified once, immediately
after initially loading the ComRV support Pythong script.'''
    set_doc = "Set the minimum ComRV entry size."
    show_doc = "Show the minimum ComRV entry size."
    def __init__ (self):
        gdb.Parameter.__init__ (self, "comrv min-entry-size",
                                gdb.COMMAND_STACK,
                                gdb.PARAM_ZUINTEGER)
        self.value = DEFAULT_MIN_COMRV_CACHE_ENTRY_SIZE_IN_BYTES

    def get_show_string (self, value):
        return ("Minimum ComRV entry size, in bytes, is %s." % (value))

# Instance of parameter object.  Use the value field of this object.
min_entry_size = min_overlay_entry_size_parameter ()

#=====================================================================#

# Print STRING as a debug message if OVERLAY_DEBUG is True.
def debug (string):
    global overlay_debug

    if not overlay_debug:
        return

    print (string)

# Helper class, create an instance of this to temporarily turn on
# debug for the enclosing scope, and turn debug off when we leave the
# scope.
class temp_debug_on:
    def __init__ (self):
        global overlay_debug
        self._old_overlay_debug = overlay_debug
        overlay_debug = True

    def __del__ (self):
        global overlay_debug
        overlay_debug = self._old_overlay_debug

#=====================================================================#

# Thanks to: https://stackoverflow.com/a/32031543/3228495
def sign_extend (value, bits):
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)

# Wrapper around access to the global configuration parameter.
def get_comrv_min_entry_size ():
    global min_entry_size
    return min_entry_size.value

# Class to wrap reading memory.  Provides an API for reading unsigned
# values of various sizes from memory.
class mem_reader:
    # Read a value LENGTH bytes long from ADDRESS.  The returned value
    # is unsigned.
    @staticmethod
    def _read_generic (address, length):
        inf = gdb.selected_inferior ()
        b = inf.read_memory (address, length)
        shift = 0
        val = 0
        for i in range(len(b)):
            t = ord (b[i])
            t <<= shift
            val |= t
            shift += 8

        return val

    @staticmethod
    def read_8_bit (address):
        return mem_reader._read_generic ((address & 0xffffffff), 1)

    @staticmethod
    def read_16_bit (address):
        return mem_reader._read_generic ((address & 0xffffffff), 2)

    @staticmethod
    def read_32_bit (address):
        return mem_reader._read_generic ((address & 0xffffffff), 4)

# The Overlay Cache Area is defined by a start and end label, this is
# the area into which code (and data?) is loaded in order to use it.
# This area is divided into "pages", each page is (currently) 512
# bytes (0x200) in size, but this can be modified by the user.
# The overlay tables are loaded into the last page of this cache
# area.
class overlay_data:
    _instance = None

    # Holds information about all the groups and multi-groups.
    class _overlay_group_data:
        def __init__ (self, groups, multi_groups, multi_group_table):
            self._groups = groups
            self._multi_groups = multi_groups
            self._multi_group_table = multi_group_table

        def get_group (self, index):
            return self._groups[index]

        def get_group_count (self):
            return len (self._groups)

        def get_multi_group (self, index):
            return self._multi_groups[index]

        def get_multi_group_count (self):
            return len (self._multi_groups)

        def get_token_from_multi_group_table (self, index):
            return self._multi_group_table[index]

    # Holds information about a single group.
    class _overlay_group:
        def __init__ (self, base_address, size_in_bytes):
            self._base_address = base_address
            self._size_in_bytes = size_in_bytes

        def base_address (self):
            return self._base_address

        def size_in_bytes (self):
            return self._size_in_bytes

    # Holds information about a single multi-group.
    class _overlay_multi_group:
        def __init__ (self, number, index, tokens):
            self._number = number
            self._index = index
            self._tokens = tokens

        def tokens (self):
            return self._tokens

        def index (self):
            return self._index

        def number (self):
            return self._number

    # A class to describe an area of memory.  This serves as a base
    # class for the cache region descriptor, and the storage region
    # descriptor classes.
    class _memory_region:
        # The START is the first address within the region, while END
        # is the first address just beyond the region.
        def __init__ (self, start, end):
            self._start_address = start
            self._end_address = end

        # Returns the first address within the region.
        def start_address (self):
            return self._start_address

        # Return the first address past the end of the region.
        def end_address (self):
            return self._end_address

    # A static description of the overlay cache area.  This is the
    # area of memory into which overlays are loaded so they can be
    # used.
    class _cache_descriptor (_memory_region):
        def __init__ (self, start, end):
            super (overlay_data._cache_descriptor, self).__init__ (start, end)

        # Return the address for the start of the cache region.
        def base_address (self):
            return self.start_address ()

        # Return the total size of the cache in bytes, including the tables
        # region.
        def size_in_bytes (self):
            return self.end_address () - self.start_address ()

        # Return the number of entries that are available for holding
        # overlays.  This excludes the area that is given up to hold the
        # overlay tables.  Currently the tables are copied into the last entry
        # in the cache.
        def number_of_working_entries (self):
            entry_size = self.entry_size_in_bytes ()
            return ((self.size_in_bytes () / entry_size)
                    - (self.tables_size_in_bytes () / entry_size))

        # Return the total number of entries that are in the cache, this
        # includes any entries being used to hold the overlay tables.
        def total_number_of_entries (self):
            entry_size = self.entry_size_in_bytes ()
            return (self.cache_size_in_bytes () / entry_size)

        # The address of the overlay tables within the cache.  Currently these
        # are always in the last entry of the cache, and are one entry in size.
        def tables_base_address (self):
            entry_size = self.entry_size_in_bytes ()
            return self.end_address () - self.tables_size_in_bytes ()

        # Return the size of the overlay tables region in bytes.  This is
        # currently always a single page of the cache.
        def tables_size_in_bytes (self):
            return self.entry_size_in_bytes ()

        # Return the size in bytes of a single entry (or page) within the
        # cache.
        def entry_size_in_bytes (self):
            return get_comrv_min_entry_size ()

    # A class that describes the overlay systems storage area.  This
    # is the area of memory from which the overlays are loaded.  The
    # debug information will refer to this area,
    class _storage_descriptor (_memory_region):
        def __init__ (self, start, end):
            super (overlay_data._storage_descriptor, self).__init__ (start, end)

    # A wrapper class to hold all the different information we loaded from
    # target memory.  An instance of this is what we return from the fetch
    # method.
    class _overlay_data_inner:
        def __init__ (self, cache_descriptor, storage_descriptor, groups_data,
                      is_multi_group):
            self._cache_descriptor = cache_descriptor
            self._groups_data = groups_data
            self._storage_descriptor = storage_descriptor
            self._is_multi_group = is_multi_group

        def cache (self):
            return self._cache_descriptor

        def storage (self):
            return self._storage_descriptor

        def group (self, index):
            return self._groups_data.get_group (index)

        def group_count (self):
            return self._groups_data.get_group_count ()

        def multi_group (self, index):
            return self._groups_data.get_multi_group (index)

        def multi_group_count (self):
            return self._groups_data.get_multi_group_count ()

        def is_multi_group_enabled (self):
            return self._is_multi_group

        def get_token_from_multi_group_table (self, index):
            return self._groups_data.get_token_from_multi_group_table (index)

        def comrv_initialised (self):
            return (not self._groups_data == None)

    # Read the group offset for overlay group GROUP_NUMBER.  The
    # overlay data starts at address BASE_ADDRESS in memory.
    #
    # Return the offset in bytes for the specified overlay group.
    @staticmethod
    def _read_overlay_offset (base_address, end_address, group_number):
        base_address = base_address + (2 * group_number)
        if ((base_address + 1) >= end_address):
            raise RuntimeError ("out of bounds access while reading offset "
                                + "table for group %d" % (group_number))
        scaled_offset = mem_reader.read_16_bit (base_address)
        offset = get_comrv_min_entry_size () * scaled_offset
        return offset

    # Read a 32-bit overlay token from the multi-group table.  ADDRESS
    # is the exact address from which the token should be loaded.
    @staticmethod
    def _read_overlay_token (address):
        token = mem_reader.read_32_bit (address)
        return token

    # Load information about all of the groups and multi-groups from the
    # overlay cache tables, and return an instance of an object holding all of
    # this data.
    @staticmethod
    def _load_group_data (table_start, table_size, storage_desc,
                          multi_group_offset):

        def _load_overlay_groups (table_start, table_end, storage_start):
            groups = list ()

            # Read all of the overlay group offsets from memory, adding
            # entries to the overlay group list as we go.
            grp = 0

            # Read the offset of the very first overlay group.  This
            # should always be 0, but lets check it anyway.
            prev_offset \
                = overlay_data._read_overlay_offset (table_start,
                                                     table_end,
                                                     grp)
            if (prev_offset != 0):
                raise RuntimeError ("offset of first overlay group is 0x%x not 0"
                                    % (prev_offset))
            while (True):
                # Read the offset for the start of the next overlay group.
                next_offset \
                    = overlay_data._read_overlay_offset (table_start,
                                                         table_end,
                                                         (grp + 1))

                # An offset of 0 indicates the end of the group table.
                if (next_offset == 0):
                    break

                # Calculate the size of this overlay group, and create an
                # object to represent it.
                size = next_offset - prev_offset
                groups.append (overlay_data.
                               _overlay_group (storage_start + prev_offset, size))
                grp += 1
                prev_offset = next_offset

            return groups

        def _load_overlay_multi_groups (table_start, table_end):
            multi_groups = list ()
            all_tokens = list ()

            # The start and end of the region containing the
            # multi-group table.
            mg_start = table_start
            mg_end = table_end

            # A number assigned to each multi-group.  Starts at 0, and
            # increments by one for each multi-group.
            mg_num = 0

            # An index assigned to each multi-group.  This is the
            # index of the first member of the multi-group.
            mg_idx = 0

            # Used to track the index into the multi-group table.
            idx = 0

            # The tokens within the current multi-group.
            mg_tokens = list ()

            while (mg_start < mg_end):
                # Read a 32-bit overlay token from the multi-group table.
                ovly_token = overlay_data._read_overlay_token (mg_start)
                all_tokens.append (ovly_token)
                idx += 1

                # A token of 0 indicates the end of a multi-group.
                if (ovly_token == 0):
                    # If this is the first entry in a multi-group then we
                    # have reached the end of all multi-group data, and
                    # we're done.
                    if (len (mg_tokens) == 0):
                        break
                    # Otherwise, we've reached the end of this
                    # multi-group, but there might be more after this.
                    # Finalise this multi-group, and prepare to parse the
                    # next.
                    else:
                        multi_groups.append (overlay_data.
                                             _overlay_multi_group (mg_num,
                                                                   mg_idx,
                                                                   mg_tokens))
                        # Now reset ready to read the next multi-group.
                        mg_num += 1
                        mg_idx = idx
                        mg_tokens = list ()
                # Otherwise a non-zero token is a member of the multi-group.
                else:
                    mg_tokens.append (ovly_token)
                mg_start += 4		# The size of one overlay token.
            return multi_groups, all_tokens

        storage_start = storage_desc.start_address ()
        if (multi_group_offset >= 0):
            table_end = table_start + multi_group_offset
        else:
            table_end = table_start + table_size

        groups = _load_overlay_groups (table_start,
                                       table_end,
                                       storage_start)

        if (multi_group_offset >= 0):
            table_end = table_start + table_size
            table_start += multi_group_offset
            multi_groups, all_tokens \
                = _load_overlay_multi_groups (table_start, table_end)
        else:
            multi_groups = list ()
            all_tokens = list ()

        return (overlay_data.
                _overlay_group_data (groups, multi_groups, all_tokens))

    # Read the address of symbol NAME from the inferior, return the
    # address as an integer.  If an error is thrown (missing symbol?)
    # then None is returned.
    @staticmethod
    def _read_symbol_address_as_integer (name):
        try:
            return int (gdb.parse_and_eval ("&%s" % (name)))
        except:
            return None

    # Read the value of symbol NAME from the inferior, return the
    # value as an integer.  If the symbol can't be read (missing
    # symbol?) then return None.
    @staticmethod
    def _read_symbol_value_as_integer (name):
        try:
            return int (gdb.parse_and_eval ("%s" % (name)))
        except:
            return None

    # Load from target memory information about the overlay cache and the
    # overlay groups.
    @staticmethod
    def fetch ():
        if (overlay_data._instance != None):
            return overlay_data._instance

        # The overlay cache is defined by two symbols, a start and end
        # symbol.  Read these and create a cache descriptor object.
        cache_start = overlay_data.\
                      _read_symbol_address_as_integer \
				(OVERLAY_CACHE_START_SYMBOL)
        cache_end = overlay_data.\
                    _read_symbol_address_as_integer \
				(OVERLAY_CACHE_END_SYMBOL)
        if (cache_start and cache_end):
            cache_desc = overlay_data._cache_descriptor (cache_start, cache_end)
        else:
            cache_desc = None

        # Similarly, the storage area, where overlays are loaded from, is
        # defined by a start and end symbol.
        storage_start = overlay_data.\
                        _read_symbol_address_as_integer \
				(OVERLAY_STORAGE_START_SYMBOL)
        storage_end = overlay_data.\
                        _read_symbol_address_as_integer \
				(OVERLAY_STORAGE_END_SYMBOL)
        if (storage_start and storage_end):
            storage_desc \
                = overlay_data._storage_descriptor (storage_start, storage_end)
        else:
            storage_desc = None

        # This is the offset to the start of the multi-group table
        # from the start of the overlay tables.  We set this to -1
        # here, if this ComRV doesn't have multi-group support then
        # this is left as -1.
        multi_group_offset = -1

        # Finally, if ComRV has been initialised then load the current state
        # from memory.
        init_been_called = overlay_data.\
                           _read_symbol_value_as_integer (INIT_SYMBOL)
        if (init_been_called):
            try:
                multi_group_offset = overlay_data.\
			_read_symbol_value_as_integer (MULTI_GROUP_OFFSET_SYMBOL)
                # The multi-group offset is held in the number of
                # 2-byte chunks, so convert this into a byte offset.
                multi_group_offset *= 2
            except:
                pass
            groups_data = overlay_data.\
                          _load_group_data (cache_desc.tables_base_address (),
                                            cache_desc.tables_size_in_bytes (),
                                            storage_desc, multi_group_offset)
        else:
            groups_data = None

        is_multi_group = multi_group_offset > 0

        # Now package all of the components into a single class
        # instance that we return.  We only cache the object if ComRV
        # has been initialised, in this way we shouldn't get stuck
        # with a cached, not initialised object.
        obj = overlay_data._overlay_data_inner (cache_desc, storage_desc,
                                                groups_data, is_multi_group)
        if (init_been_called):
            overlay_data._instance = obj
        return obj

    # Discard the information loaded from the cache.  The next time fetch is
    # called the information will be reread.
    @staticmethod
    def clear ():
        overlay_data._instance = None

# Class for walking the overlay data structures and calling the
# visit_mapped_overlay method for every mapped overlay group.
class mapped_overlay_group_walker:
    # Call this to walk the overlay manager data structures in memory and
    # call the visit_mapped_overlay method for each mapped overlay group.
    def walk_mapped_overlays (self):
        # Grab the data that describes the current overlay state.
        ovly_data = overlay_data.fetch ()
        if (not ovly_data.comrv_initialised ()):
            self.comrv_not_initialised ()
            return

        # Now walk the overlay cache and see which entries are mapped in.
        index = 0
        while (index < ovly_data.cache ().number_of_working_entries ()):
            group = gdb.parse_and_eval (OVERLAY_CACHE_AT_INDEX_TO_GROUP_ID % (index))
            group = int (group)
            offset = None

            if (group != 0xffff):
                # Found an entry that is mapped in.
                group_desc = ovly_data.group (group)
                src_addr = group_desc.base_address ()
                length = group_desc.size_in_bytes ()
                dst_addr = (ovly_data.cache ().base_address ()
                            + (index
                               * ovly_data.cache ().entry_size_in_bytes ()))

                if (not self.visit_mapped_overlay (src_addr, dst_addr, length,
                                                index, group)):
                    break

                offset = gdb.parse_and_eval (OVERLAY_CACHE_AT_INDEX_TO_SIZE_IN_MIN_UNITS % (index))
                offset = int (offset)
                if (offset == 0):
                    # Something has gone wrong here.  An overlay
                    # appears to be mapped, but has 0 size.  Maybe we
                    # could load the overlay size from the static
                    # data, after all we do know it.  For now just
                    # force to 1 so we don't get stuck.
                    offset = 1
            else:
                # Found an entry that is not currently mapped.
                offset = 1

            # Move to the next cache entry.
            index += offset

    # Default implementation of visit_mapped_overlay, sub-classes should
    # override this method.  Return true to continue walking the list of
    # mapped overlays, or return false to stop.
    def visit_mapped_overlay (self, src_addr, dst_addr, length,
                              cache_index, group_number):
        return True

    # Default implementation of comrv_not_initialised, sub-classes
    # should override this method.  This is called if
    # walk_mapped_overlays is called before ComRV is initialised.
    def comrv_not_initialised (self):
        None

def print_current_comrv_state ():
    ovly_data = overlay_data.fetch ()
    if (not ovly_data.comrv_initialised ()):
        print ("ComRV not yet initialisd:")
        print ("      %s: %d"
               % (INIT_SYMBOL,
                  int (gdb.parse_and_eval ("%s" % (INIT_SYMBOL)))))
        print ("     &%s: 0x%x"
               % (INIT_SYMBOL,
                  int (gdb.parse_and_eval ("&%s" % (INIT_SYMBOL)))))
        return

    print ("Overlay Regions:")
    print ("  %-9s%-12s%-12s%-8s" % ("Region", "Start", "End", "Size"))
    print ("  %-9s0x%-10x0x%-10x0x%-6x"
           % ("storage",
              ovly_data.storage ().start_address (),
              ovly_data.storage ().end_address (),
              (ovly_data.storage ().end_address () -
               ovly_data.storage ().start_address ())))
    print ("  %-9s0x%-10x0x%-10x0x%-6x"
           % ("cache",
              ovly_data.cache ().start_address (),
            ovly_data.cache ().end_address (),
              (ovly_data.cache ().end_address () -
               ovly_data.cache ().start_address ())))
    print ("")
    print ("Overlay groups:")
    grp_num = 0
    while (grp_num < ovly_data.group_count ()):
        grp = ovly_data.group (grp_num)
        if (grp == None):
            break
        if (grp_num == 0):
            print ("  %-7s%-12s%-12s%-8s" % ("Group", "Start", "End", "Size"))
        print ("  %-7d0x%-10x0x%-10x0x%-6x"
               % (grp_num, grp.base_address (),
                  (grp.base_address () + grp.size_in_bytes ()),
                  grp.size_in_bytes ()))
        grp_num += 1
    print ("")
    print ("Overlay multi-groups:")
    if (ovly_data.is_multi_group_enabled ()):
        grp_num = 0
        while (grp_num < ovly_data.multi_group_count ()):
            mg = ovly_data.multi_group (grp_num)
            if (grp_num == 0):
                print ("  %6s%-7s%-12s%-9s%-8s"
                       % ("", "", "", "Overlay", "Function"))
                print ("  %-6s%-7s%-12s%-9s%-8s"
                       % ("Num", "Index", "Token", "Group", "Offset"))
            else:
                print ("  %-6s%-7s%-12s%-9s%-8s"
                       % ("---", "---", "---", "---", "---"))
            for token in mg.tokens ():
                g = (token >> 1) & 0xffff
                offset = ((token >> 17) & 0x3ff) * 4
                print ("  %-6d%-7d0x%08x  %-9d0x%-8x"
                       % (grp_num, mg.index (), token, g, offset))
            grp_num += 1
    else:
        print ("  Not supported in this ComRV build.")
    print ("")
    print ("Current overlay mappings:")
    # Class to walk the currently mapped overlays and print a summary.
    class print_mapped_overlays (mapped_overlay_group_walker):
        def __init__ (self):
            self._shown_header = False
            self.walk_mapped_overlays ()
            if (not self._shown_header):
                self.nothing_is_mapped ()

        def visit_mapped_overlay (self, src_addr, dst_addr, length,
                                  cache_index, group_number):
            if (not self._shown_header):
                self._shown_header = True
                print ("  %-7s%-9s%-12s%-12s%-8s"
                       % ("Cache", "Overlay", "Storage", "Cache", ""))
                print ("  %-7s%-9s%-12s%-12s%-8s"
                       % ("Index", "Group", "Addr", "Addr", "Size"))

            print ("  %-7d%-9d0x%-10x0x%-10x0x%-8x"
                   % (cache_index, group_number, src_addr, dst_addr, length))
            return True

        def nothing_is_mapped (self):
            print ("  No overlays groups are currently mapped.")

    print_mapped_overlays ()

# Model a single frame on the ComRV stack.
class comrv_stack_frame:
    def __init__ (self, addr, is_mg):
        self._frame_addr = addr
        self._return_addr = mem_reader.read_32_bit (addr)
        self._token = mem_reader.read_32_bit (addr + 4)
        self._offset = mem_reader.read_16_bit (addr + 8)
        self._align = mem_reader.read_8_bit (addr + 10)
        if (is_mg):
            if (self._offset == 12):
                index = mem_reader.read_8_bit (addr + 11)
                self._mg_index = sign_extend (index, 8)
            else:
                index = mem_reader.read_16_bit (addr + 14)
                self._mg_index = sign_extend (index, 16)
        else:
            self._mg_index = 0

    def frame_address (self):
        return (self._frame_addr & 0xffffffff)

    def return_address (self):
        return (self._return_addr & 0xffffffff)

    def token (self):
        return (self._token & 0xffffffff)

    def align (self):
        return ((self._align & 0xffff) * get_comrv_min_entry_size ())

    def multi_group_index (self):
        return (self._mg_index & 0xffff)

    def offset (self):
        return self._offset

class comrv_prefix_command (gdb.Command):
    def __init__ (self):
        gdb.Command.__init__ (self, "comrv", gdb.COMMAND_NONE, gdb.COMPLETE_NONE, True)

# The class represents a new GDB command 'comrv status' that reads the current
# overlay status and prints a summary to the screen.
class comrv_status_command (gdb.Command):
    '''Display the current state of ComRV overlays.

This command only works once ComRV has been initialised.

The information displayed includes the addresses of the ComRV
cache and storage areas, a summary of all the groups and multi-groups
as well as which overlay groups are currently mapped in.'''
    def __init__ (self):
        gdb.Command.__init__ (self, "comrv status", gdb.COMMAND_NONE)

    def invoke (self, args, from_tty):
        print_current_comrv_state ()

        # Discard the cached cache data, incase we ran this command at the
        # wrong time and the cache information is invalid.  This will force
        # GDB to reload the information each time this command is run.
        overlay_data.clear ()

# The class represents a new GDB command 'comrv stack' that reads the
# current ComRV stack, and prints a summary.  This is related to, but
# not the same as backtracing, as the backtrace interprets the ComRV
# stack, while this is a raw peek into the stack.
class comrv_stack_command (gdb.Command):
    '''Display the ComRV stack.

This is different to the normal GDB backtrace in that backtrace interprets
the ComRV stack, while this command just dumps the raw stack contents.

This requires ComRV to be initialised before any stack can be displayed.

The fields are:
    Frame - The frame number, just an index, with the lowest number being
            the most recent frame.
  Address - The address of the frame, that is the value of register t3 that
            points to this frame.
      R/A - The return address field for this stack frame.
    Token - The token field for this stack frame.
Alignment - The alignment field from the ComRV stack, alignment to size of
            maximum group size.
      M/G - (Only in multi-group builds of ComRV) The overlay group token
            for the specific overlay that was used.
     Size - The size of this stack frame.  The outermost frame should have
            a size of 0xdead, this indicates the end of the stack.'''

    def __init__ (self):
        gdb.Command.__init__ (self, "comrv stack", gdb.COMMAND_NONE)

    def invoke (self, args, from_tty):
        ovly_data = overlay_data.fetch ()
        is_initialised = ovly_data.comrv_initialised ()
        is_mg = ovly_data.is_multi_group_enabled ()
        overlay_data.clear ()

        if (not is_initialised):
            print ("ComRV not yet initialised")
            return

        t3_addr = int (gdb.parse_and_eval ("$t3"))
        depth = 0
        if (is_mg):
            print ("%5s %10s %10s %10s %10s %6s %6s"
                   % ("Frame", "Address", "R/A", "Token", "Alignment", "M/G", "Size"))
        else:
            print ("%5s %10s %10s %10s %10s %6s"
                   % ("Frame", "Address", "R/A", "Token", "Alignment", "Size"))
        while (True):
            frame = comrv_stack_frame (t3_addr, is_mg)
            if (is_mg):
                print ("%5s %10s %10s %10s %10s %6s %6s"
                       % (("#%d" % (depth)),
                          ("0x%08x" % (frame.frame_address ())),
                          ("0x%08x" % (frame.return_address ())),
                          ("0x%08x" % (frame.token ())),
                          ("0x%08x" % (frame.align ())),
                          ("0x%04x" % (frame.multi_group_index ())),
                          ("0x%x" % (frame.offset ()))))
            else:
                print ("%5s %10s %10s %10s %10s %6s"
                       % (("#%d" % (depth)),
                          ("0x%08x" % (frame.frame_address ())),
                          ("0x%08x" % (frame.return_address ())),
                          ("0x%08x" % (frame.token ())),
                          ("0x%08x" % (frame.align ())),
                          ("0x%x" % (frame.offset ()))))
            depth += 1
            if (frame.offset () == 0xdead):
                break
            t3_addr += frame.offset ()


# The command 'parse-comrv' existed once, but is now deprecated.
class ParseComRV (gdb.Command):
    'Parse the ComRV data table.'

    def __init__ (self):
        gdb.Command.__init__ (self, "parse-comrv", gdb.COMMAND_NONE)

    def invoke (self, args, from_tty):
        raise RuntimeError ("this command is deprecated, use 'comrv status' instead")

class MyOverlayManager (gdb.OverlayManager):
    def __init__ (self):
        gdb.OverlayManager.__init__ (self, True)
        # STOP !
        #
        # No code should be placed here that assumes the ELF being
        # debugged is currently loaded.  It is highly likely that this
        # file is sourced before the ELF being debugged is loaded (for
        # example in Eclipse) in which case non of the required
        # symbols will exist.
        pass

    def get_region_data (self):
        ovly_data = overlay_data.fetch ()
        debug ("Setting up overlay manager region data:")
        debug ("Cache:")
        debug ("  Start: 0x%x" % (ovly_data.cache ().start_address ()))
        debug ("    End: 0x%x" % (ovly_data.cache ().end_address ()))
        debug ("Storage:")
        debug ("  Start: 0x%x" % (ovly_data.storage ().start_address ()))
        debug ("    End: 0x%x" % (ovly_data.storage ().end_address ()))
        self.set_storage_region (ovly_data.storage ().start_address (),
                                 ovly_data.storage ().end_address ())
        self.set_cache_region (ovly_data.cache ().start_address (),
                               ovly_data.cache ().end_address ())

    def __del__ (self):
        print ('Destructor called for MyOverlayManager')

    # Return a string, where GDB should place the overlay event
    # breakpoint.
    def event_symbol_name (self):
        debug ("In Python code, event_symbol_name")
        return "_ovly_debug_event"

    # Return an integer, the number of multi-groups.  Return the
    # special value -1 to indicate ComRV is not yet initialised, and
    # so we don't know how many multi-groups there are, in this case
    # GDB will ask again later.  Otherwise return a value greater
    # than, or equal to zero, GDB will cache this answer and not ask
    # again.
    def get_multi_group_count (self):
        debug ("In Python get_multi_group_count method")
        ovly_data = overlay_data.fetch ()
        if (not ovly_data.comrv_initialised ()):
            # If ComRV is not yet initialised then return -1 to
            # indicate that GDB should ask again later.
            return -1
        return ovly_data.multi_group_count ()

    # For multi-group number ID return a list of all the storage area
    # addresses of all the functions within this multi-group.
    def get_multi_group (self, id):
        ovly_data = overlay_data.fetch ()
        if (not ovly_data.comrv_initialised ()):
            raise RuntimeError ("ComRV not yet initialised")
        if (id >= ovly_data.multi_group_count ()):
            raise RuntimeError ("Multi-group index out of range")
        res = list ()
        mg = ovly_data.multi_group (id)
        for token in mg.tokens ():
            g = (token >> 1) & 0xffff
            offset = ((token >> 17) & 0x3ff) * 4
            addr = self.get_group_storage_area_address (g)
            addr += offset
            res.append (addr)
        return res

    # Return the overlay token from the multi-group table at INDEX.
    def get_multi_group_table_by_index (self, index):
        ovly_data = overlay_data.fetch ()
        if (not ovly_data.comrv_initialised ()):
            raise RuntimeError ("ComRV not yet initialised")
        if (not ovly_data.is_multi_group_enabled ()):
            raise RuntimeError ("Multi-group not supported")
        return ovly_data.get_token_from_multi_group_table (index)

    # Called to read the current state of ComRV, which overlays are
    # mapped in.  Should call the ADD_MAPPING method on ourselves
    # (implemented inside GDB) to inform GDB about an active overlay
    # mapping.
    def read_mappings (self):
        debug ("In Python code, read_mappings")

        global overlay_debug
        if (overlay_debug):
            print_current_comrv_state ()

        # Class to walk mapped overlays and add them to the list of currently
        # mapped overlays.
        class map_overlays (mapped_overlay_group_walker):
            def __init__ (self, manager):
                self._manager = manager
                self.walk_mapped_overlays ()

            def visit_mapped_overlay (self, src_addr, dst_addr, length,
                                      cache_index, group_number):
                self._manager.add_mapping (src_addr, dst_addr, length)
                return True

        # Create an instance of the previous class, this does all the work in
        # its constructor.
        map_overlays (self)

        debug ("All mappings added")
        return True

    # Return the address of the label that a function will return too
    # if it is returning through the ComRV enginee.  If the label
    # can't be found (maybe ComRV is not in use) then return 0.
    def get_comrv_return_from_callee_label (self):
        try:
            name = COMRV_RETURN_FROM_CALLEE_LABEL
            return int (gdb.parse_and_eval ("&%s" % (name)))
        except:
            return 0

    # Unwind the ComRV stack frame at ADDR.  Return a list of two
    # elements.  The first element is the return address extracted
    # from the ComRV stack frame, and the second element is the
    # address of the previous ComRV stack frame.
    def unwind_comrv_stack_frame (self, addr):
        global max_group_size

        ovly_data = overlay_data.fetch ()
        if (not ovly_data.comrv_initialised ()):
            raise RuntimeError ("ComRV is not initialised")
        is_mg = ovly_data.is_multi_group_enabled ()

        # Create a stack frame object at ADDR to represent the stack
        # frame we are unwinding.
        frame = comrv_stack_frame (addr, is_mg)

        comrv_return_addr = self.get_comrv_return_from_callee_label ()
        if (comrv_return_addr == 0):
            raise RuntimeError ("ComRV unwinding is disabled")
        while (frame.return_address () == comrv_return_addr):
            if (frame.offset () == 0xdead):
                raise RuntimeError ("hit top of ComRV stack (1)")

            addr += frame.offset ()
            frame = comrv_stack_frame (addr, is_mg)

        if (frame.return_address () == 0
            and frame.token () == 0):
            raise RuntimeError ("hit top of ComRV stack (2)")

        addr += frame.offset ()

        ra = frame.return_address ()
        cache_start = ovly_data.cache ().start_address ()
        cache_end = ovly_data.cache ().end_address ()
        if (ra >= cache_start and ra < cache_end):
            prev_frame = comrv_stack_frame (addr, is_mg)

            if ((prev_frame.token () & 0x1) != 0x1):
                raise RuntimeError ("returning to overlay function, "
                                    + "second stack frame token is "
                                    + str (prev_frame.token ()))

            token = prev_frame.token ()
            if (((token >> 31) & 0x1) == 0x1):
                if (prev_frame.multi_group_index () == -1):
                    raise RuntimeError ("mutli-group stack token with no valid token index")
                idx = prev_frame.multi_group_index ()
                token = self.get_multi_group_table_by_index (idx)

            group_id = (token >> 1) & 0xffff
            func_offset = (token >> 17) & 0x3ff
            alignment = prev_frame.align ()
            group_size = ovly_data.group (group_id).size_in_bytes ()
            max_grp_size = max_group_size.value
            group_offset = (func_offset
                            + ((frame.return_address () - func_offset
                                - alignment) & (max_grp_size - 1)))
            base_addr = ovly_data.group (group_id).base_address ()
            ra = base_addr + group_offset

            debug ("Unwinder:")
            debug ("  frame.return_addr: " + hex (frame.return_address ()))
            debug ("  group_id: " + str (group_id))
            debug ("  func_offset: " + hex (func_offset))
            debug ("  alignment: " + hex (alignment))
            debug ("  group_size: " + hex (group_size))
            debug ("  max_group_size: " + hex (max_grp_size))
            debug ("  group_offset: " + hex (group_offset))
            debug ("  base_addr: " + hex (base_addr))
            debug ("  ra: " + str (ra))

        return ra, addr

    # This is a temporary hack needed to support backtracing.
    # Ideally, the whole backtracing stack unwind would move into
    # python, and then this function would not be needed, however, to
    # do that we will need some serious changes to how GDB's stack
    # unwinder works.
    #
    # For now then we need to expose a mechanism by which we can find
    # the size of a group given its group ID.
    def get_group_size (self, id):
        ovly_data = overlay_data.fetch ()
        if (not ovly_data.comrv_initialised ()):
            # Maybe we should through an error in this case?
            return 0

        group_desc = ovly_data.group (id)
        tmp = group_desc.size_in_bytes ()

        debug ("Size of group %d is %d" % (id, tmp))
        return tmp

    # Return the base address, within the storage area, for overlay
    # group ID.  The base address is the first address of an overlay
    # group.
    def get_group_storage_area_address (self, id):
        debug ("get_group_storage_area_address (%d) = ..." % (id))
        ovly_data = overlay_data.fetch ()
        if (not ovly_data.comrv_initialised ()):
            raise RuntimeError ("ComRV not initialised, overlay "
                                + "storage area address unknown")

        group_desc = ovly_data.group (id)
        tmp = group_desc.base_address ()

        debug ("get_group_storage_area_address (%d) = 0x%x"
               % (id, tmp))
        return tmp

    # Return a value indicating if multi-group is compiled into this
    # ComRV.  Return -1 for we don't know (yet), 1 for multi-group is
    # compiled in, or 0 for multi-group is not compiled in.
    def is_multi_group_enabled (self):
        ovly_data = overlay_data.fetch ()
        if (not ovly_data.comrv_initialised ()):
            return -1;

        if (ovly_data.is_multi_group_enabled ()):
            return 1;

        return 0

# Create an instance of the command class.
ParseComRV ()

comrv_prefix_command ()
comrv_status_command ()
comrv_stack_command ()

# Create an instance of the overlay manager class.
MyOverlayManager ()

gdb.execute ("overlay auto", False, False)


# This line is commented out, but left in at the request of WD.
# Turning this packet off will force GDB to make use of read/write
# software breakpoints, however, on some targets these don't appear to
# play well, probably with pipeline caching or some such.
#
# gdb.execute ("set remote software-breakpoint-packet off", False, False)
