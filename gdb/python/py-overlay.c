/* Python interface to overlay manager

   Copyright (C) 2019 Free Software Foundation, Inc.

   This file is part of GDB.

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <http://www.gnu.org/licenses/>.  */

#include "defs.h"
#include "python-internal.h"
#include "python.h"
#include "overlay.h"
#include "arch-utils.h"

/* Constants for method names defined on a Python class.  */
#define EVENT_SYMBOL_NAME_METHOD "event_symbol_name"
#define READ_MAPPINGS_METHOD "read_mappings"
#define ADD_MAPPING_METHOD "add_mapping"
#define GET_GROUP_SIZE_METHOD "get_group_size"
#define GET_GROUP_BASE_ADDR_METHOD "get_group_unmapped_base_address"
#define GET_MULTI_GROUP_COUNT_METHOD "get_multi_group_count"

#define SET_STORAGE_REGION_METHOD "set_storage_region"
#define SET_CACHE_REGION_METHOD "set_cache_region"

/* Declare. */
struct gdbpy_ovly_mgr_object;
static PyObject * py_overlay_manager_add_mapping (PyObject *self,
						  PyObject *args,
						  PyObject *kwargs);

/* An implementation of an overlay manager that delegates out to Python
   code that the user can easily override.  */

class gdb_py_overlay_manager : public gdb_overlay_manager
{
public:
  gdb_py_overlay_manager (gdbpy_ovly_mgr_object *obj, bool reload_on_event)
    : gdb_overlay_manager (reload_on_event),
      m_obj (obj)
  {
    Py_INCREF (m_obj);
  }

  ~gdb_py_overlay_manager ()
  {
    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (python_gdbarch, current_language);

    Py_DECREF (m_obj);
  }

  std::string event_symbol_name () const override
  {
    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (get_current_arch (), current_language);

    PyObject *obj = (PyObject *) m_obj;

    /* The base class gdb.OverlayManager provides a default implementation
       so this method should always be found.  */
    static const char *method_name = EVENT_SYMBOL_NAME_METHOD;
    gdb_assert (PyObject_HasAttrString (obj, method_name));
    gdbpy_ref<> result (PyObject_CallMethod (obj, method_name, NULL));
    if (result == NULL)
      return "";

    gdb::unique_xmalloc_ptr<char>
      symbol_name (python_string_to_host_string (result.get ()));
    if (symbol_name == NULL)
      return "";

    std::string tmp (symbol_name.get ());
    return tmp;
  }

  std::unique_ptr<std::vector<mapping>> read_mappings () override
  {
    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (get_current_arch (), current_language);

    m_mappings.reset (new std::vector<mapping>);
    PyObject *obj = (PyObject *) m_obj;

    /* The base class gdb.OverlayManager provides a default implementation
       so this method should always be found.  */
    static const char *method_name = READ_MAPPINGS_METHOD;
    gdb_assert (PyObject_HasAttrString (obj, method_name));
    gdbpy_ref<> result (PyObject_CallMethod (obj, method_name, NULL));
    if (result == NULL || !PyObject_IsTrue (result.get ()))
      {
	/* TODO: We get here if the call to read_mappings failed.  We're
	   about to return an empty list of mappings, having ignored any
	   errors, but maybe we should do more to pass error back up the
	   stack?  */
        if (debug_overlay)
          fprintf_unfiltered (gdb_stdlog,
                              "Reading overlay mappings failed\n");

	/* Failed to read current mappings, discard any partial mappings we
	   found and return the empty vector.  */
	m_mappings->clear ();
	return std::move (m_mappings);
      }

    /* Return the vector of mappings we created.  */
    return std::move (m_mappings);
  }

  ULONGEST get_group_size (int group_id) override
  {
    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (get_current_arch (), current_language);

    PyObject *obj = (PyObject *) m_obj;

    /* The base class gdb.OverlayManager provides a default implementation
       so this method should always be found.  */
    static const char *method_name = GET_GROUP_SIZE_METHOD;
    if (!PyObject_HasAttrString (obj, method_name))
      /* TODO: Should we throw an error here?  */
      return 0;

    gdbpy_ref<> id_obj (PyLong_FromLongLong ((long long) group_id));
    if (id_obj == NULL)
      /* TODO: Should we throw an error here?  */
      return 0;

    gdbpy_ref<> method_obj (PyString_FromString (method_name));
    gdb_assert (method_name != NULL);
    gdbpy_ref<> result (PyObject_CallMethodObjArgs (obj, method_obj.get (),
                                                    id_obj.get (), NULL));
    if (result == NULL)
      error (_("missing result object"));

    if (PyLong_Check (result.get ()))
      return PyLong_AsUnsignedLongLong (result.get ());
    else if (PyInt_Check (result.get ()))
      return (ULONGEST) PyInt_AsLong (result.get ());
    else
      error ("result is not numeric");
  }

  CORE_ADDR get_group_unmapped_base_address (int group_id) override
  {
    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (get_current_arch (), current_language);

    PyObject *obj = (PyObject *) m_obj;

    /* The base class gdb.OverlayManager provides a default implementation
       so this method should always be found.  */
    static const char *method_name = GET_GROUP_BASE_ADDR_METHOD;
    if (!PyObject_HasAttrString (obj, method_name))
      /* TODO: Should we throw an error here?  */
      return 0;

    gdbpy_ref<> id_obj (PyLong_FromLongLong ((long long) group_id));
    if (id_obj == NULL)
      /* TODO: Should we throw an error here?  */
      return 0;

    gdbpy_ref<> method_obj (PyString_FromString (method_name));
    gdb_assert (method_name != NULL);
    gdbpy_ref<> result (PyObject_CallMethodObjArgs (obj, method_obj.get (),
                                                    id_obj.get (), NULL));
    if (result == NULL)
      error (_("missing result object"));

    if (PyLong_Check (result.get ()))
      return (CORE_ADDR) PyLong_AsUnsignedLongLong (result.get ());
    else if (PyInt_Check (result.get ()))
      return (CORE_ADDR) PyInt_AsLong (result.get ());
    else
      error ("result is not an address (or numeric)");
  }

  CORE_ADDR get_multi_group_table_by_index (int index) override
  {
    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (get_current_arch (), current_language);

    PyObject *obj = (PyObject *) m_obj;

    /* The base class gdb.OverlayManager provides a default implementation
       so this method should always be found.  */
    static const char *method_name = "get_multi_group_table_by_index";
    if (!PyObject_HasAttrString (obj, method_name))
      /* TODO: Should we throw an error here?  */
      return 0;

    gdbpy_ref<> idx_obj (PyLong_FromLongLong ((long long) index));
    if (idx_obj == NULL)
      /* TODO: Should we throw an error here?  */
      return 0;

    gdbpy_ref<> method_obj (PyString_FromString (method_name));
    gdb_assert (method_name != NULL);
    gdbpy_ref<> result (PyObject_CallMethodObjArgs (obj, method_obj.get (),
                                                    idx_obj.get (), NULL));
    if (result == NULL)
      error (_("missing result object"));

    if (PyLong_Check (result.get ()))
      return (CORE_ADDR) PyLong_AsUnsignedLongLong (result.get ());
    else if (PyInt_Check (result.get ()))
      return (CORE_ADDR) PyInt_AsLong (result.get ());
    else
      error ("result is not an address (or numeric)");
  }

  /* Check to see if the Python overlay manager has any multi group
     information, if it does then load it and return true, otherwise,
     return false.

     Once we have loaded multi-group information then this is cached, and
     we always return true in the future.  */
  bool has_multi_groups () override
  {
    if (m_multi_group_count >= 0)
      return m_multi_group_count > 0;

    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (get_current_arch (), current_language);

    gdb_assert (m_multi_group_count == -1);

    PyObject *obj = (PyObject *) m_obj;

    /* Get the number of multi-groups, the base class has a default
       implementation of the get_multi_group_count method, so we know this
       should always exist.  */
    static const char *method_name = GET_MULTI_GROUP_COUNT_METHOD;
    gdb_assert (PyObject_HasAttrString (obj, method_name));
    gdbpy_ref<> result (PyObject_CallMethod (obj, method_name, NULL));
    if (result == NULL)
      error ("missing result object");

    LONGEST val;
    if (PyLong_Check (result.get ()))
      val = PyLong_AsLongLong (result.get ());
    else if (PyInt_Check (result.get ()))
      val = (LONGEST) PyInt_AsLong (result.get ());
    else
      error ("result is not numeric");
    m_multi_group_count = std::max ((LONGEST) -1, val);

    if (m_multi_group_count > 0)
      {
        /* Load details of each multi-group.  */
        static const char *method_name2 = "get_multi_group";
        if (!PyObject_HasAttrString (obj, method_name2))
          error ("missing method %s on python overlay manager", method_name2);
        gdbpy_ref<> method_obj2 (PyString_FromString (method_name2));

        for (int i = 0; i < m_multi_group_count; ++i)
          {
            /* Call into the python code and get back a list of addresses.  */
            gdbpy_ref<> id_obj (PyLong_FromLongLong ((long long) i));
            if (id_obj == NULL)
              error ("failed to create python integer object");

            gdbpy_ref<> lst_obj (PyObject_CallMethodObjArgs (obj, method_obj2.get (),
                                                             id_obj.get (),
                                                             NULL));
            if (lst_obj == NULL)
              error (_("missing result object"));

            if (!PyList_CheckExact (lst_obj.get ()))
              error (_("not a list from %s"), method_name2);

            if (debug_overlay)
              fprintf_unfiltered (gdb_stdlog,
                                  "Multi-group %d:\n", i);

            multi_group_desc desc;
            for (int j = 0; j < PyList_Size (lst_obj.get ()); ++j)
              {
                PyObject *itm = PyList_GetItem (lst_obj.get (), j);
                CORE_ADDR addr;

                if (PyLong_Check (itm))
                  addr = (CORE_ADDR) PyLong_AsUnsignedLongLong (itm);
                else if (PyInt_Check (itm))
                  addr = (CORE_ADDR) PyInt_AsLong (itm);
                else
                  error ("result is not an address (or numeric)");

                if (debug_overlay)
                  fprintf_unfiltered (gdb_stdlog,
                                      "  (%d) %s\n", j,
                                      core_addr_to_string (addr));

                if (j == 0)
                  {
                    CORE_ADDR start, end;

                    if (!find_pc_partial_function (addr, NULL, &start, &end))
                      error ("unable to compute function bounds");
                    if (start != addr)
                      error ("multi-group address is not start of a function");
                    if (debug_overlay)
                      fprintf_unfiltered (gdb_stdlog,
                                          "    Function: %s -> %s\n",
                                          core_addr_to_string (start),
                                          core_addr_to_string (end));
                    desc.base = start;
                    desc.len = end - start;
                  }
                else
                  desc.alt_addr.push_back (addr);
              }
            m_multi_groups.push_back (desc);
          }
      }

    return (m_multi_group_count > 0);
  }

  /* See overlay.h.  */

  std::vector<CORE_ADDR> find_multi_group (CORE_ADDR addr,
                                           CORE_ADDR *offset) override
  {
    if (m_multi_group_count <= 0)
      return {};

    for (int i = 0; i < m_multi_group_count; ++i)
      {
        if (addr >= m_multi_groups[i].base
            && addr < (m_multi_groups[i].base + m_multi_groups[i].len))
          {
            *offset = addr - m_multi_groups[i].base;
            return m_multi_groups[i].alt_addr;
          }
      }

    return {};
  }

  /* See overlay.h.  */

  CORE_ADDR map_to_primary_multi_group_addr (CORE_ADDR addr) override
  {
    if (m_multi_group_count <= 0)
      return addr;

    for (int i = 0; i < m_multi_group_count; ++i)
      {
        if (addr >= m_multi_groups[i].base
            && addr < (m_multi_groups[i].base + m_multi_groups[i].len))
          return addr;

        for (const CORE_ADDR &alt : m_multi_groups[i].alt_addr)
          {
            /* ADDR is within an alternative address range for a
               multi-group, return the equivalent address within the
               primary address range.  */
            if (addr >= alt && addr < alt + m_multi_groups[i].len)
              return m_multi_groups[i].base + (addr - alt);
          }
      }

    return addr;
  }

  /* See overlay.h.  */

  bool is_multi_group_enabled () override
  {
    if (m_is_multi_group_enabled)
      return *m_is_multi_group_enabled;

    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (get_current_arch (), current_language);

    PyObject *obj = (PyObject *) m_obj;

    /* The base class gdb.OverlayManager provides a default implementation
       so this method should always be found.  */
    static const char *method_name = "is_multi_group_enabled";
    if (!PyObject_HasAttrString (obj, method_name))
      /* TODO: Should we throw an error here?  */
      return false;

    gdbpy_ref<> result (PyObject_CallMethod (obj, method_name, NULL));
    if (result == NULL)
      error (_("missing result object"));

    /* Answer can be any integer.  A value less than 0 indicates that
       Python doesn't know (yet) so we reply with false, but don't cache
       the answer.  An reply greater than 0 indicates we know overlay
       support is compiled in, and we can cache the answer, while an
       response of 0 indicates that we know overlay support is not compiled
       in, and we can cache the answer.  */
    int answer;
    if (PyLong_Check (result.get ()))
      answer = (int) PyLong_AsLongLong (result.get ());
    else if (PyInt_Check (result.get ()))
      answer = (int) PyInt_AsLong (result.get ());
    else
      error ("result is not numeric");

    if (answer < 0)
      return false;

    m_is_multi_group_enabled.emplace (answer > 0);
    return *m_is_multi_group_enabled;
  }

private:

  void load_region_data (void) override
  {
    gdb_assert (gdb_python_initialized);
    gdbpy_enter enter_py (get_current_arch (), current_language);

    PyObject *obj = (PyObject *) m_obj;

    if (debug_overlay)
      fprintf_unfiltered (gdb_stdlog,
                          "loading region data from python\n");

    /* The base class gdb.OverlayManager provides a default implementation
       so this method should always be found.  */
    static const char *method_name = "get_region_data";
    if (!PyObject_HasAttrString (obj, method_name))
      error ("no python method get_region_data");

    gdbpy_ref<> result (PyObject_CallMethod (obj, method_name, NULL));
  }

  void add_mapping (CORE_ADDR src, CORE_ADDR dst, ULONGEST len)
  {
    /* TODO: Maybe we should throw an error in this case rather than just
       ignoring the attempt to add a new mapping.  */
    if (m_mappings == nullptr)
      return;

    if (debug_overlay)
      fprintf_unfiltered (gdb_stdlog,
                          "py_overlay_manager_add_mapping, "
                          "src = %s, dst = %s, len = %s\n",
                          core_addr_to_string (src),
                          core_addr_to_string (dst),
                          pulongest (len));

    mapping m (src, dst, len);
    m_mappings->push_back (m);
  }

  friend PyObject * py_overlay_manager_add_mapping (PyObject *self, PyObject *args, PyObject *kwargs);

  /* The Python object associated with this overlay manager.  */
  gdbpy_ovly_mgr_object *m_obj;

  /* This vector is non-null only for the duration of read_mappings, and
     is added to by calls to add_mapping.  */
  std::unique_ptr<std::vector<mapping>> m_mappings;

  /* The number of multi-groups.  Initially -1 meaning no information
     known about multi-groups.  Once ComRV is initialised this will be set
     to 0 or more.  */
  int m_multi_group_count = -1;

  struct multi_group_desc
  {
    /* The primary address for the function in this multi-group.  */
    CORE_ADDR base;

    /* The length of this function.  */
    size_t len;

    /* Alternative addresses for the function in this multi-group.  */
    std::vector<CORE_ADDR> alt_addr;
  };

  /* One descriptor for each multi-group.  */
  std::vector<multi_group_desc> m_multi_groups;

  /* Set when we know if multi-group is compiled into ComRV.  */
  gdb::optional<bool> m_is_multi_group_enabled;
};

/* Wrapper around a Python object, provides a mechanism to find the overlay
   manager object from the Python object.  */

struct gdbpy_ovly_mgr_object {
  /* Python boilerplate, must come first.  */
  PyObject_HEAD

  /* Point at the actual overlay manager we created when this Python object
     was created.  This object is owned by the generic overlay management
     code within GDB.  */
  gdb_py_overlay_manager *manager;
};

/* Initializer for OverlayManager object, it takes no parameters.  */

static int
py_overlay_manager_init (PyObject *self, PyObject *args, PyObject *kwargs)
{
  static const char *keywords[] = { "reload_on_event", NULL };
  PyObject *reload_on_event_obj = NULL;

  if (!gdb_PyArg_ParseTupleAndKeywords (args, kwargs, "O", keywords,
					&reload_on_event_obj))
    return -1;

  int reload_on_event = PyObject_IsTrue (reload_on_event_obj);
  if (reload_on_event == -1)
    return -1;

  gdbpy_ovly_mgr_object *obj = (gdbpy_ovly_mgr_object *) self;
  std::unique_ptr <gdb_py_overlay_manager> mgr
    (new gdb_py_overlay_manager (obj, reload_on_event));
  obj->manager = mgr.get ();
  overlay_manager_register (std::move (mgr));
  return 0;
}

/* Deallocate OverlayManager object.  */

static void
py_overlay_manager_dealloc (PyObject *self)
{
  /* TODO: Should ensure that this object is no longer registered as the
     overlay manager for GDB otherwise bad things will happen.  */

  /* Set this pointer to null not because we have to, but to protect
     against any uses after we deallocate.  */
  gdbpy_ovly_mgr_object *obj = (gdbpy_ovly_mgr_object *) self;
  obj->manager = nullptr;

  /* Now ask Python to free this object.  */
  Py_TYPE (self)->tp_free (self);
}

/* Python function which returns the name of the overlay event symbol.
   This is the fallback, users should be overriding this method.  If we
   get here then return None to indicate that there is no event symbol.  */

static PyObject *
py_overlay_manager_event_symbol_name (PyObject *self, PyObject *args)
{
  Py_RETURN_NONE;
}

/* Default implementation of the "read_mappings" method on the
   gdb.OverlayManager class, this is called if the user provided overlay
   manager doesn't override.  This registers no mappings, and just returns
   None.  */

static PyObject *
py_overlay_manager_read_mappings (PyObject *self, PyObject *args)
{
  Py_RETURN_NONE;
}

/* Python function which returns the number of multi-groups.  This is the
   fallback, users should be overriding this method.  If we get here then
   return zero to indicate that there are no multi-groups.  */

static PyObject *
py_overlay_manager_get_multi_group_count (PyObject *self, PyObject *args)
{
  return PyLong_FromLong (0);
}

/* Called to register an overlay mapping.  Takes three parameters 'src',
   'dst', and 'len', which describe an active overlay mapping.

   This method should only be called from within the 'read_mappings' call
   to record the mappings.  Any other calls to this method will be
   ignored.

   TODO: I'm not really happy with this API, I would much rather that the
   'read_mappings' call return a list of all the mappings or throw an
   error if something goes wrong.  */

static PyObject *
py_overlay_manager_add_mapping (PyObject *self, PyObject *args, PyObject *kwargs)
{
  gdbpy_ovly_mgr_object *obj = (gdbpy_ovly_mgr_object *) self;

  static const char *keywords[] = { "src", "dst", "len", NULL };
  PyObject *src_obj, *dst_obj, *len_obj;
  CORE_ADDR src, dst;
  ULONGEST len;

  if (!gdb_PyArg_ParseTupleAndKeywords (args, kwargs, "OOO", keywords,
					&src_obj, &dst_obj, &len_obj))
    return nullptr;

  if (get_addr_from_python (src_obj, &src) < 0)
    return nullptr;

  if (get_addr_from_python (dst_obj, &dst) < 0)
    return nullptr;

  if (PyLong_Check (len_obj))
    len = PyLong_AsUnsignedLongLong (len_obj);
  else if (PyInt_Check (len_obj))
    len = (ULONGEST) PyInt_AsLong (len_obj);
  else
    {
      PyErr_SetString (PyExc_TypeError, _("Invalid length argument."));
      return nullptr;
    }

  obj->manager->add_mapping (src, dst, len);
  Py_RETURN_NONE;
}

/* ... */

static PyObject *
py_overlay_manager_set_storage_region (PyObject *self, PyObject *args,
                                       PyObject *kwargs)
{
  gdbpy_ovly_mgr_object *obj = (gdbpy_ovly_mgr_object *) self;

  static const char *keywords[] = { "start", "end", NULL };
  PyObject *start_addr_obj, *end_addr_obj;
  CORE_ADDR start_addr, end_addr;

  if (!gdb_PyArg_ParseTupleAndKeywords (args, kwargs, "OO", keywords,
					&start_addr_obj, &end_addr_obj))
    return nullptr;

  if (get_addr_from_python (start_addr_obj, &start_addr) < 0)
    return nullptr;

  if (get_addr_from_python (end_addr_obj, &end_addr) < 0)
    return nullptr;

  std::vector<std::pair<CORE_ADDR, CORE_ADDR>> regions;
  regions.push_back ({start_addr, end_addr});
  obj->manager->set_storage_regions (regions);
  Py_RETURN_NONE;
}

/* Called from the Python code to register the cache region.  Takes two
   parameters, 'start' and 'end', both are addresses.  The start address
   is the first address in the region, and end is the first address beyond
   the region.

   TODO: I'm not happy with this API, I would rather that we get passed a
   list of cache regions as I suspect that it might be true that we can
   have more than one.  */

static PyObject *
py_overlay_manager_set_cache_region (PyObject *self, PyObject *args,
                                       PyObject *kwargs)
{
  gdbpy_ovly_mgr_object *obj = (gdbpy_ovly_mgr_object *) self;

  static const char *keywords[] = { "start", "end", NULL };
  PyObject *start_addr_obj, *end_addr_obj;
  CORE_ADDR start_addr, end_addr;

  if (!gdb_PyArg_ParseTupleAndKeywords (args, kwargs, "OO", keywords,
					&start_addr_obj, &end_addr_obj))
    return nullptr;

  if (get_addr_from_python (start_addr_obj, &start_addr) < 0)
    return nullptr;

  if (get_addr_from_python (end_addr_obj, &end_addr) < 0)
    return nullptr;

  std::vector<std::pair<CORE_ADDR, CORE_ADDR>> regions;
  regions.push_back ({start_addr, end_addr});
  obj->manager->set_cache_regions (regions);
  Py_RETURN_NONE;
}

/* Methods on gdb.OverlayManager.  */

static PyMethodDef overlay_manager_object_methods[] =
{
  { EVENT_SYMBOL_NAME_METHOD, py_overlay_manager_event_symbol_name,
    METH_NOARGS, "Return a string, the name of the event symbol." },
  { READ_MAPPINGS_METHOD, py_overlay_manager_read_mappings,
    METH_NOARGS, "Register the current overlay mappings." },
  { ADD_MAPPING_METHOD, (PyCFunction) py_overlay_manager_add_mapping,
    METH_VARARGS | METH_KEYWORDS,
    "Callback to register a single overlay mapping." },
  { SET_STORAGE_REGION_METHOD,
    (PyCFunction) py_overlay_manager_set_storage_region,
    METH_VARARGS | METH_KEYWORDS,
    "Callback to register the location of the storage region."},
  { SET_CACHE_REGION_METHOD,
    (PyCFunction) py_overlay_manager_set_cache_region,
    METH_VARARGS | METH_KEYWORDS,
    "Callback to register the location of the cache region."},
  { GET_MULTI_GROUP_COUNT_METHOD, py_overlay_manager_get_multi_group_count,
    METH_NOARGS, "Return an integer, the number of multi-groups." },
  { NULL } /* Sentinel.  */
};

void
py_overlay_manager_finalize (void)
{
  overlay_manager_register (nullptr);
}

/* Structure defining an OverlayManager object type.  */

PyTypeObject overlay_manager_object_type =
{
  PyVarObject_HEAD_INIT (NULL, 0)
  "gdb.OverlayManager",		  /*tp_name*/
  sizeof (gdbpy_ovly_mgr_object), /*tp_basicsize*/
  0,				  /*tp_itemsize*/
  py_overlay_manager_dealloc,	  /*tp_dealloc*/
  0,				  /*tp_print*/
  0,				  /*tp_getattr*/
  0,				  /*tp_setattr*/
  0,				  /*tp_compare*/
  0,				  /*tp_repr*/
  0,				  /*tp_as_number*/
  0,				  /*tp_as_sequence*/
  0,				  /*tp_as_mapping*/
  0,				  /*tp_hash */
  0,				  /*tp_call*/
  0,				  /*tp_str*/
  0,				  /*tp_getattro*/
  0,				  /*tp_setattro */
  0,				  /*tp_as_buffer*/
  Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,  /*tp_flags*/
  "GDB overlay manager object",	  /* tp_doc */
  0,				  /* tp_traverse */
  0,				  /* tp_clear */
  0,				  /* tp_richcompare */
  0,				  /* tp_weaklistoffset */
  0,				  /* tp_iter */
  0,				  /* tp_iternext */
  overlay_manager_object_methods, /* tp_methods */
  0,				  /* tp_members */
  0,				  /* tp_getset */
  0,				  /* tp_base */
  0,				  /* tp_dict */
  0,				  /* tp_descr_get */
  0,				  /* tp_descr_set */
  0,				  /* tp_dictoffset */
  py_overlay_manager_init,	  /* tp_init */
  0,				  /* tp_alloc */
};

/* Initialize the Python overlay code.  */
int
gdbpy_initialize_overlay (void)
{
  overlay_manager_object_type.tp_new = PyType_GenericNew;
  if (PyType_Ready (&overlay_manager_object_type) < 0)
    return -1;

  if (gdb_pymodule_addobject (gdb_module, "OverlayManager",
			      (PyObject *) &overlay_manager_object_type) < 0)
    return -1;
  return 0;
}
