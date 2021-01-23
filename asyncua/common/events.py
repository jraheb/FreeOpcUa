import copy

from asyncua import ua
import asyncua
from ..ua.uaerrors import UaError
from .ua_utils import get_node_subtypes


class Event:
    """
    OPC UA Event object.
    This is class in inherited by the common event objects such as BaseEvent,
    other auto standard events and custom events
    Events are used to trigger events on server side and are
    sent to clients for every events from server

    Developper Warning:
    On server side the data type of attributes should be known, thus
    add properties using the add_property method!!!
    """

    def __init__(self, emitting_node=ua.ObjectIds.Server):
        self.server_handle = None
        self.select_clauses = None
        self.event_fields = None
        self.data_types = {}
        self.emitting_node = emitting_node
        if isinstance(emitting_node, ua.NodeId):
            self.emitting_node = emitting_node
        else:
            self.emitting_node = ua.NodeId(emitting_node)
        # save current attributes
        self.internal_properties = list(self.__dict__.keys())[:] + ["internal_properties"]

    def __str__(self):
        return "{0}({1})".format(
            self.__class__.__name__,
            [str(k) + ":" + str(v) for k, v in self.__dict__.items() if k not in self.internal_properties])
    __repr__ = __str__

    def add_property(self, name, val, datatype):
        """
        Add a property to event and store its data type
        """
        setattr(self, name, val)
        self.data_types[name] = datatype

    def add_variable(self, name, val, datatype):
        """
        Add a variable to event and store its data type
        variables are able to have properties as children
        """
        setattr(self, name, val)
        self.data_types[name] = datatype

    def get_event_props_as_fields_dict(self):
        """
        convert all properties and variables of the Event class to a dict of variants
        """
        field_vars = {}
        for key, value in vars(self).items():
            if not key.startswith("__") and key not in self.internal_properties:
                field_vars[key] = ua.Variant(value, self.data_types[key])
        return field_vars

    @staticmethod
    def from_field_dict(fields):
        """
        Create an Event object from a dict of name and variants
        """
        ev = Event()
        for k, v in fields.items():
            ev.add_property(k, v.Value, v.VariantType)
        return ev

    def to_event_fields_using_subscription_fields(self, select_clauses):
        """
        Using a new select_clauses and the original select_clauses
        used during subscription, return a field list
        """
        fields = []
        for sattr in select_clauses:
            for idx, o_sattr in enumerate(self.select_clauses):
                if sattr.BrowsePath == o_sattr.BrowsePath and sattr.AttributeId == o_sattr.AttributeId:
                    fields.append(self.event_fields[idx])
                    break
        return fields

    def to_event_fields(self, select_clauses):
        """
        return a field list using a select clause and the object properties
        """
        fields = []
        for sattr in select_clauses:
            name = self.simple_attribute_to_field_name(sattr)
            try:
                val = getattr(self, name)
            except AttributeError:
                field = ua.Variant(None)
            else:
                if val is None:
                    field = ua.Variant(None)
                else:
                    field = ua.Variant(copy.deepcopy(val), self.data_types[name])
            fields.append(field)
        return fields

    @staticmethod
    def from_event_fields(select_clauses, fields):
        """
        Instantiate an Event object from a select_clauses and fields
        """
        ev = Event()
        ev.select_clauses = select_clauses
        ev.event_fields = fields
        for idx, sattr in enumerate(select_clauses):
            name = Event.simple_attribute_to_field_name(sattr)
            ev.add_property(name, fields[idx].Value, fields[idx].VariantType)
        return ev

    @staticmethod
    def simple_attribute_to_field_name(simpleAttribute):
        if len(simpleAttribute.BrowsePath) == 0:
            name = simpleAttribute.AttributeId.name
        else:
            name = simpleAttribute.BrowsePath[0].Name
            # Append the sub-property of a VariableType with '/'
            iter_paths = iter(simpleAttribute.BrowsePath)
            next(iter_paths)                
            for path in iter_paths:
                name += '/' + path.Name
        return name


async def get_filter_from_event_type(eventtypes):
    evfilter = ua.EventFilter()
    evfilter.SelectClauses = await select_clauses_from_evtype(eventtypes)
    evfilter.WhereClause = await where_clause_from_evtype(eventtypes)
    return evfilter


async def append_new_field_to_select_clauses(field, select_clauses, parent_variable):
    already_selected = [op.BrowsePath for op in select_clauses if not op.BrowsePath]
    browsePath = []
    if parent_variable:
        browsePath.append(await parent_variable.read_browse_name())
    browsePath.append(await field.read_browse_name())
    if browsePath not in already_selected:
        op = ua.SimpleAttributeOperand()
        op.AttributeId = ua.AttributeIds.Value
        op.BrowsePath = browsePath
        select_clauses.append(op)    


async def select_clauses_from_evtype(evtypes):
    select_clauses = []
    for evtype in evtypes:
        for property in await get_event_properties_from_type_node(evtype):
            await append_new_field_to_select_clauses(property, select_clauses, None)
        for variable in await get_event_variables_from_type_node(evtype):
            await append_new_field_to_select_clauses(variable, select_clauses, None)
            for subproperty in await variable.get_properties():
                await append_new_field_to_select_clauses(subproperty, select_clauses, variable)
    return select_clauses


async def where_clause_from_evtype(evtypes):
    cf = ua.ContentFilter()
    el = ua.ContentFilterElement()
    # operands can be ElementOperand, LiteralOperand, AttributeOperand, SimpleAttribute
    # Create a clause where the generate event type property EventType
    # must be a subtype of events in evtypes argument

    # the first operand is the attribute event type
    op = ua.SimpleAttributeOperand()
    # op.TypeDefinitionId = evtype.nodeid
    op.BrowsePath.append(ua.QualifiedName("EventType", 0))
    op.AttributeId = ua.AttributeIds.Value
    el.FilterOperands.append(op)
    # now create a list of all subtypes we want to accept
    subtypes = []
    for evtype in evtypes:
        for st in await get_node_subtypes(evtype):
            subtypes.append(st.nodeid)
    subtypes = list(set(subtypes))  # remove duplicates
    for subtypeid in subtypes:
        op = ua.LiteralOperand()
        op.Value = ua.Variant(subtypeid)
        el.FilterOperands.append(op)
    el.FilterOperator = ua.FilterOperator.InList
    cf.Elements.append(el)
    return cf


async def select_event_fields_from_type_node(node, fieldSelector):
    fields = []
    curr_node = node
    while True:
        fields.extend(await fieldSelector(curr_node))
        if curr_node.nodeid.Identifier == ua.ObjectIds.BaseEventType:
            break
        parents = await curr_node.get_referenced_nodes(
            refs=ua.ObjectIds.HasSubtype, direction=ua.BrowseDirection.Inverse, includesubtypes=True
        )
        if len(parents) != 1:  # Something went wrong
            return None
        curr_node = parents[0]
    return fields


async def get_event_properties_from_type_node(node):
    return await select_event_fields_from_type_node(node, lambda n: n.get_properties())


async def get_event_variables_from_type_node(node):
    return await select_event_fields_from_type_node(node, lambda n: n.get_variables())


async def get_event_obj_from_type_node(node):
    """
    return an Event object from an event type node
    """
    if node.nodeid.NamespaceIndex == 0:
        if node.nodeid.Identifier in asyncua.common.event_objects.IMPLEMENTED_EVENTS.keys():
            return asyncua.common.event_objects.IMPLEMENTED_EVENTS[node.nodeid.Identifier]()

    parent_identifier, parent_eventtype = await _find_parent_eventtype(node)

    class CustomEvent(parent_eventtype):

        def __init__(self):
            parent_eventtype.__init__(self)
            self.EventType = node.nodeid

        async def add_new_property(self, property, parent_variable):
            name = (await property.read_browse_name()).Name
            if parent_variable:
                parent_name = (await parent_variable.read_browse_name()).Name
                name = f'{parent_name}/{name}'
            val = await property.read_data_value()
            self.add_property(name, val.Value.Value, val.Value.VariantType)

        async def add_new_variable(self, variable):
            name = (await variable.read_browse_name()).Name
            val = await variable.read_data_value()
            self.add_variable(name, val.Value.Value, await variable.get_data_type_as_variant_type())

        async def init(self):
            curr_node = node
            while curr_node.nodeid.Identifier != parent_identifier:
                for prop in await curr_node.get_properties():
                    await self.add_new_property(prop, None)
                for var in await curr_node.get_variables():
                    await self.add_new_variable(var)
                    # Add the sub-properties of the VariableType
                    for prop in await var.get_properties():
                        await self.add_new_property(prop, var)
                parents = await curr_node.get_referenced_nodes(refs=ua.ObjectIds.HasSubtype,
                                                               direction=ua.BrowseDirection.Inverse,
                                                               includesubtypes=True)
                if len(parents) != 1:  # Something went wrong
                    raise UaError("Parent of event type could not be found")
                curr_node = parents[0]

            self._freeze = True

    ce = CustomEvent()
    await ce.init()
    return ce


async def _find_parent_eventtype(node):
    """
    """
    parents = await node.get_referenced_nodes(refs=ua.ObjectIds.HasSubtype, direction=ua.BrowseDirection.Inverse,
                                              includesubtypes=True)

    if len(parents) != 1:   # Something went wrong
        raise UaError("Parent of event type could not be found")
    if parents[0].nodeid.NamespaceIndex == 0:
        if parents[0].nodeid.Identifier in asyncua.common.event_objects.IMPLEMENTED_EVENTS.keys():
            return parents[0].nodeid.Identifier, asyncua.common.event_objects.IMPLEMENTED_EVENTS[parents[0].nodeid.Identifier]
    return await _find_parent_eventtype(parents[0])
