package vn.logisimmcp.live;

import com.cburch.logisim.circuit.Circuit;
import com.cburch.logisim.circuit.CircuitState;
import com.cburch.logisim.circuit.Propagator;
import com.cburch.logisim.circuit.SubcircuitFactory;
import com.cburch.logisim.circuit.WidthIncompatibilityData;
import com.cburch.logisim.circuit.Wire;
import com.cburch.logisim.comp.Component;
import com.cburch.logisim.comp.ComponentFactory;
import com.cburch.logisim.comp.EndData;
import com.cburch.logisim.data.Attribute;
import com.cburch.logisim.data.AttributeSet;
import com.cburch.logisim.data.BitWidth;
import com.cburch.logisim.data.Bounds;
import com.cburch.logisim.data.Direction;
import com.cburch.logisim.data.Location;
import com.cburch.logisim.data.Value;
import com.cburch.logisim.file.LogisimFile;
import com.cburch.logisim.instance.Instance;
import com.cburch.logisim.instance.InstanceComponent;
import com.cburch.logisim.instance.InstanceState;
import com.cburch.logisim.instance.Port;
import com.cburch.logisim.instance.StdAttr;
import com.cburch.logisim.proj.Project;
import com.cburch.logisim.std.wiring.Clock;
import com.cburch.logisim.std.wiring.Pin;
import com.cburch.logisim.std.wiring.Tunnel;
import com.cburch.logisim.tools.AddTool;
import com.cburch.logisim.tools.Library;
import com.cburch.logisim.tools.Tool;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Read-only understanding of a Logisim project: component catalog, component geometry and ports,
 * the electrical netlist exactly as Logisim connects it, diagnostics, and simulation in a private
 * circuit state (the window's own simulation is never disturbed unless explicitly asked).
 */
final class LiveInspector {
  private LiveInspector() {}

  // ------------------------------------------------------------------ catalog

  static Map<String, Object> catalog(Project project, String libraryFilter, String query) {
    final LogisimFile file = project.getLogisimFile();
    final String q = query == null ? "" : query.toLowerCase(Locale.ROOT).trim();
    final List<Object> libs = new ArrayList<>();
    final List<Library> all = new ArrayList<>(file.getLibraries());
    all.add(0, file);
    for (final Library lib : all) {
      final String desc = lib == file ? "" : file.getLoader().getDescriptor(lib);
      if (libraryFilter != null && !libraryFilter.isEmpty() && !libraryFilter.equals(desc)
          && !libraryFilter.equalsIgnoreCase(lib.getName())) {
        continue;
      }
      final List<Object> tools = new ArrayList<>();
      collectTools(lib, "", q, tools, lib != file);
      if (tools.isEmpty()) continue;
      final Map<String, Object> m = new LinkedHashMap<>();
      m.put("library", lib == file ? "(this project: subcircuits)" : desc);
      m.put("name", lib.getName());
      m.put("display", lib.getDisplayName());
      m.put("components", tools);
      libs.add(m);
    }
    final Map<String, Object> result = new LinkedHashMap<>();
    result.put("libraries", libs);
    return result;
  }

  private static void collectTools(Library lib, String group, String q, List<Object> out, boolean recurse) {
    for (final Tool tool : lib.getTools()) {
      if (!(tool instanceof AddTool add)) continue;
      final String name = tool.getName();
      final String display = add.getDisplayName();
      if (!q.isEmpty()
          && !name.toLowerCase(Locale.ROOT).contains(q)
          && (display == null || !display.toLowerCase(Locale.ROOT).contains(q))
          && !group.toLowerCase(Locale.ROOT).contains(q)) {
        continue;
      }
      final Map<String, Object> m = new LinkedHashMap<>();
      m.put("name", name);
      if (display != null && !display.equals(name)) m.put("display", display);
      if (!group.isEmpty()) m.put("group", group);
      out.add(m);
    }
    if (!recurse) return; // the project file lists its circuits; its libraries come separately
    for (final Library sub : lib.getLibraries()) {
      collectTools(sub, group.isEmpty() ? sub.getDisplayName() : group + "/" + sub.getDisplayName(), q, out, true);
    }
  }

  // ------------------------------------------------------------------ attributes

  @SuppressWarnings({"unchecked", "rawtypes"})
  static Map<String, Object> attributeInfo(Attribute<?> attribute, Object value) {
    final Attribute<Object> attr = (Attribute<Object>) attribute;
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("name", attr.getName());
    final String display = safeDisplay(attr);
    if (display != null && !display.equals(attr.getName())) m.put("display", display);
    m.put("value", safeString(attr, value));
    final String simple = attr.getClass().getSimpleName();
    String type = switch (simple) {
      case "BooleanAttribute" -> "boolean";
      case "DirectionAttribute" -> "direction";
      case "OptionAttribute" -> "option";
      case "IntegerAttribute", "IntegerRangeAttribute" -> "integer";
      case "HexIntegerAttribute", "HexLongAttribute" -> "hex integer";
      case "StringAttribute", "MultilineStringAttribute" -> "text";
      case "FontAttribute" -> "font";
      case "ColorAttribute" -> "color";
      case "DoubleAttribute" -> "number";
      case "LocationAttribute" -> "location";
      default -> value instanceof BitWidth ? "bit width" : simple;
    };
    final Object vals = field(attr, "vals");
    if (vals instanceof Object[] options) {
      final List<Object> list = new ArrayList<>();
      for (final Object o : options) list.add(safeString(attr, o));
      m.put("options", list);
      if (type.equals(simple)) type = "option";
    }
    final Object choices = field(attr, "choices");
    if (choices instanceof BitWidth[] widths && widths.length > 0) {
      m.put("min", widths[0].getWidth());
      m.put("max", widths[widths.length - 1].getWidth());
    }
    final Object start = field(attr, "start");
    final Object end = field(attr, "end");
    if (start instanceof Integer s && end instanceof Integer e) {
      m.put("min", s);
      m.put("max", e);
    }
    final Object min = field(attr, "min");
    final Object max = field(attr, "max");
    if (min instanceof Integer s && max instanceof Integer e && !m.containsKey("min")) {
      m.put("min", s);
      m.put("max", e);
    }
    m.put("type", type);
    if (attr.isHidden()) m.put("hidden", true);
    return m;
  }

  private static Object field(Object target, String name) {
    for (Class<?> c = target.getClass(); c != null && c != Object.class; c = c.getSuperclass()) {
      try {
        final Field f = c.getDeclaredField(name);
        f.setAccessible(true);
        return f.get(target);
      } catch (NoSuchFieldException ignored) {
        // try the superclass
      } catch (ReflectiveOperationException | RuntimeException e) {
        return null;
      }
    }
    return null;
  }

  private static String safeDisplay(Attribute<?> attr) {
    try {
      return attr.getDisplayName();
    } catch (RuntimeException e) {
      return null;
    }
  }

  @SuppressWarnings("unchecked")
  static String safeString(Attribute<?> attr, Object value) {
    if (value == null) return null;
    try {
      return ((Attribute<Object>) attr).toStandardString(value);
    } catch (RuntimeException e) {
      return String.valueOf(value);
    }
  }

  // ------------------------------------------------------------------ ports

  private static final Pattern TTL_NAMED = Pattern.compile("(\\d+)\\s*:\\s*(\\S.*)$");
  private static final Pattern TTL_NUMBER = Pattern.compile("(\\d+)\\s*$");

  /** Port list with stable names: tooltips (TTL pin names, subcircuit pin labels) or in/out numbering. */
  static List<Map<String, Object>> ports(Component comp, int originX, int originY) {
    final List<EndData> ends = comp.getEnds();
    List<Port> portList = null;
    if (comp instanceof InstanceComponent ic) {
      try {
        portList = ic.getInstance().getPorts();
      } catch (RuntimeException ignored) {
        portList = null;
      }
    }
    final boolean ttl = comp.getFactory().getClass().getName().contains(".std.ttl.");
    // Wiring devices with a single port carry a generic "add a pin" tooltip; their port is just
    // the device itself. Other factories (subcircuits, memories, arithmetic...) name ports well.
    final String fname = comp.getFactory().getClass().getSimpleName();
    final boolean useTooltips = !(fname.equals("Pin") || fname.equals("Probe") || fname.equals("Clock")
        || fname.equals("Constant") || fname.equals("Tunnel") || fname.equals("PullResistor")
        || fname.equals("Ground") || fname.equals("Power") || fname.equals("Bit Extender"));
    int ins = 0;
    int outs = 0;
    int ios = 0;
    for (final EndData e : ends) {
      if (e == null) continue;
      switch (e.getType()) {
        case EndData.INPUT_ONLY -> ins++;
        case EndData.OUTPUT_ONLY -> outs++;
        default -> ios++;
      }
    }
    int ci = 0;
    int co = 0;
    int cb = 0;
    // Flip-flops: data inputs carry no tooltip and outputs have long descriptions; use the
    // names from every datasheet (D, T, J/K, S/R, Q, Qn) instead.
    final String factoryName = comp.getFactory().getName();
    final String[] flipFlopData =
        factoryName.endsWith("Flip-Flop")
            ? factoryName.substring(0, factoryName.indexOf(" Flip-Flop")).split("-")
            : null;
    int dataIndex = 0;
    final Set<String> used = new HashSet<>();
    final List<Map<String, Object>> result = new ArrayList<>();
    for (int i = 0; i < ends.size(); i++) {
      final EndData e = ends.get(i);
      if (e == null) continue;
      final String dir;
      final String generic;
      switch (e.getType()) {
        case EndData.INPUT_ONLY -> {
          dir = "in";
          ci++;
          generic = ins == 1 ? "in" : "in" + ci;
        }
        case EndData.OUTPUT_ONLY -> {
          dir = "out";
          co++;
          generic = outs == 1 ? "out" : "out" + co;
        }
        default -> {
          dir = "inout";
          cb++;
          generic = ios == 1 ? "io" : "io" + cb;
        }
      }
      String tip = null;
      if (portList != null && i < portList.size() && portList.get(i) != null) {
        try {
          tip = portList.get(i).getToolTip();
        } catch (RuntimeException ignored) {
          tip = null;
        }
      }
      final List<String> aliases = new ArrayList<>();
      String name = generic;
      Integer pin = null;
      if (tip != null && !tip.isBlank()) {
        final String t = tip.trim();
        if (ttl) {
          final Matcher named = TTL_NAMED.matcher(t);
          final Matcher numbered = TTL_NUMBER.matcher(t);
          if (named.find()) {
            pin = Integer.parseInt(named.group(1));
            name = named.group(2).trim();
          } else if (numbered.find()) {
            pin = Integer.parseInt(numbered.group(1));
            name = "pin" + pin;
          }
          if (t.toLowerCase(Locale.ROOT).contains("gnd") || t.toLowerCase(Locale.ROOT).contains("ground")) {
            name = "GND";
          } else if (t.toLowerCase(Locale.ROOT).contains("vcc")) {
            name = "VCC";
          }
        } else if (useTooltips) {
          name = shortName(t);
        }
      }
      if (!useTooltips && ends.size() == 1) name = "port"; // a pin/probe/tunnel: the device is the port
      if (flipFlopData != null) {
        final String lower = tip == null ? "" : tip.toLowerCase(Locale.ROOT);
        if (tip == null && "in".equals(dir) && dataIndex < flipFlopData.length) {
          name = flipFlopData[dataIndex++];
        } else if (lower.contains("complement")) {
          name = "Qn";
          aliases.add("nQ");
        } else if (lower.startsWith("clock")) {
          name = "Clock";
          aliases.add("CLK");
        } else if (lower.startsWith("clear") || lower.startsWith("reset")) {
          name = "Clear";
          aliases.add("CLR");
        } else if (lower.startsWith("preset") || lower.startsWith("set")) {
          name = "Preset";
          aliases.add("PRE");
        } else if ("out".equals(dir) && (lower.contains("current") || lower.contains("state"))) {
          name = "Q";
        } else if (lower.startsWith("enable")) {
          name = "Enable";
          aliases.add("EN");
        }
      }
      if (pin != null) aliases.add("pin" + pin);
      if (!name.equals(generic)) aliases.add(generic);
      aliases.add("p" + i);
      if (used.contains(name)) name = name + "#" + i;
      used.add(name);
      final Map<String, Object> m = new LinkedHashMap<>();
      m.put("index", i);
      m.put("name", name);
      if (tip != null && !tip.equals(name)) m.put("description", tip);
      if (pin != null) m.put("pin", pin);
      m.put("aliases", aliases);
      m.put("direction", dir);
      m.put("width", e.getWidth().getWidth());
      m.put("x", e.getLocation().getX() - originX);
      m.put("y", e.getLocation().getY() - originY);
      result.add(m);
    }
    return result;
  }

  /** "Data in: value to store" -> "Data_in"; keeps names short and usable in "id.port" references. */
  static String shortName(String tooltip) {
    String t = tooltip.trim();
    final int colon = t.indexOf(':');
    if (colon > 0 && colon <= 24) t = t.substring(0, colon).trim();
    if (t.length() > 24) t = t.substring(0, 24).trim();
    t = t.replaceAll("[\\s.]+", "_");
    return t.isEmpty() ? tooltip : t;
  }

  private static final java.awt.image.BufferedImage SCRATCH =
      new java.awt.image.BufferedImage(4, 4, java.awt.image.BufferedImage.TYPE_INT_ARGB);

  /** Body plus label text, measured with real font metrics (what the user sees on the canvas). */
  static Bounds visualBounds(Component comp) {
    final java.awt.Graphics2D g = SCRATCH.createGraphics();
    try {
      return comp.getBounds(g);
    } catch (RuntimeException e) {
      return comp.getBounds();
    } finally {
      g.dispose();
    }
  }

  static Map<String, Object> bounds(Bounds b, int originX, int originY) {
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("x", b.getX() - originX);
    m.put("y", b.getY() - originY);
    m.put("width", b.getWidth());
    m.put("height", b.getHeight());
    return m;
  }

  // ------------------------------------------------------------------ describe

  /** Geometry, ports and attributes of one component type (with optional properties applied). */
  static Map<String, Object> describe(Project project, String desc, String name, Map<String, String> props)
      throws LiveEditor.InvalidOp {
    final LogisimFile file = project.getLogisimFile();
    final ComponentFactory factory = LiveEditor.factory(file, desc, name);
    final List<String> warnings = new ArrayList<>();
    final AttributeSet attrs = LiveEditor.buildAttrs(factory, props, warnings, name);
    final Component comp;
    try {
      comp = factory.createComponent(Location.create(0, 0, false), attrs);
    } catch (RuntimeException e) {
      throw new LiveEditor.InvalidOp("Logisim could not create " + name + ": " + e.getMessage());
    }
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("library", desc == null || desc.isEmpty() ? null : desc);
    m.put("name", name);
    final String display = factory.getDisplayName();
    if (display != null && !display.equals(name)) m.put("display", display);
    m.put("anchor", "all coordinates are offsets from the component location (loc)");
    m.put("bounds", bounds(comp.getBounds(), 0, 0));
    final Bounds visual = visualBounds(comp);
    if (!visual.equals(comp.getBounds())) m.put("visual_bounds", bounds(visual, 0, 0));
    m.put("ports", ports(comp, 0, 0));
    final List<Object> attributes = new ArrayList<>();
    for (final Attribute<?> attr : attrs.getAttributes()) {
      attributes.add(attributeInfo(attr, attrs.getValue(attr)));
    }
    m.put("properties", attributes);
    if (!warnings.isEmpty()) m.put("warnings", warnings);
    return m;
  }

  /** Several describes in one round trip (used by the bridge for routing obstacles). */
  static Map<String, Object> describeMany(Project project, List<Object> specs) {
    final List<Object> out = new ArrayList<>();
    for (final Object raw : specs) {
      final Map<String, Object> s = Json.obj(raw);
      try {
        final Map<String, Object> d =
            describe(project, Json.str(s.get("lib")), Json.str(s.get("name")), LiveEditor.props(s.get("props")));
        d.remove("properties");
        out.add(d);
      } catch (LiveEditor.InvalidOp e) {
        final Map<String, Object> err = new LinkedHashMap<>();
        err.put("error", e.getMessage());
        out.add(err);
      }
    }
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("items", out);
    return m;
  }

  // ------------------------------------------------------------------ inspect

  private static final class Nets {
    final Map<Location, Location> parent = new HashMap<>();

    Location find(Location a) {
      Location root = a;
      while (true) {
        final Location p = parent.get(root);
        if (p == null || p.equals(root)) break;
        root = p;
      }
      Location cur = a;
      while (!cur.equals(root)) {
        final Location next = parent.get(cur);
        parent.put(cur, root);
        cur = next;
      }
      parent.putIfAbsent(root, root);
      return root;
    }

    void union(Location a, Location b) {
      final Location ra = find(a);
      final Location rb = find(b);
      if (!ra.equals(rb)) parent.put(ra, rb);
    }
  }

  static String libraryOf(LogisimFile file, ComponentFactory factory, Map<String, String> cache) {
    if (factory instanceof SubcircuitFactory) return null;
    final String key = factory.getClass().getName() + "|" + factory.getName();
    if (cache.containsKey(key)) return cache.get(key);
    String found = "?";
    for (final Library lib : file.getLibraries()) {
      final Tool tool = LiveEditor.findTool(lib, factory.getName());
      if (tool instanceof AddTool add && LiveEditor.sameFactory(add.getFactory(), factory)) {
        found = file.getLoader().getDescriptor(lib);
        break;
      }
    }
    cache.put(key, found);
    return found;
  }

  static String componentId(Component comp) {
    return comp.getFactory().getName() + "@" + comp.getLocation().getX() + "," + comp.getLocation().getY();
  }

  static String label(Component comp) {
    final AttributeSet attrs = comp.getAttributeSet();
    if (attrs.containsAttribute(StdAttr.LABEL)) {
      final String label = attrs.getValue(StdAttr.LABEL);
      if (label != null && !label.isBlank()) return label;
    }
    return null;
  }

  static String formatValue(Value v) {
    if (v == null) return null;
    if (v.getWidth() <= 0) return "-";
    return v.toBinaryString();
  }

  /**
   * Everything needed to understand a circuit without looking at it: components with their exact
   * bounds and absolute port coordinates, wires, nets (connectivity exactly as Logisim computes it:
   * wire ends, component ports and same-label tunnels), live values, and problems.
   */
  @SuppressWarnings("unchecked")
  static Map<String, Object> inspect(Project project, String circuitName, boolean withValues, boolean withAttributes)
      throws LiveEditor.InvalidOp {
    final LogisimFile file = project.getLogisimFile();
    final Circuit circuit = LiveEditor.circuit(file, circuitName);
    final Map<String, String> libCache = new HashMap<>();

    final List<Component> comps = new ArrayList<>(circuit.getNonWires());
    comps.sort(
        Comparator.comparingInt((Component c) -> c.getLocation().getY())
            .thenComparingInt(c -> c.getLocation().getX())
            .thenComparing(c -> c.getFactory().getName()));
    final List<Wire> wires = new ArrayList<>(circuit.getWires());
    wires.sort(
        Comparator.comparingInt((Wire w) -> w.getEnd0().getY())
            .thenComparingInt(w -> w.getEnd0().getX())
            .thenComparingInt(w -> w.getEnd1().getY())
            .thenComparingInt(w -> w.getEnd1().getX()));

    // ids: type@x,y, disambiguated if two devices of one type share an anchor
    final Map<Component, String> ids = new HashMap<>();
    final Map<String, Integer> idCount = new HashMap<>();
    for (final Component c : comps) {
      String id = componentId(c);
      final int n = idCount.merge(id, 1, Integer::sum);
      if (n > 1) id = id + "#" + n;
      ids.put(c, id);
    }
    final Map<String, Integer> labelCount = new HashMap<>();
    for (final Component c : comps) {
      final String l = label(c);
      if (l != null) labelCount.merge(l, 1, Integer::sum);
    }

    // ---- connectivity
    final Nets nets = new Nets();
    final Map<Location, Integer> wireEnds = new HashMap<>();
    for (final Wire w : wires) {
      nets.union(w.getEnd0(), w.getEnd1());
      wireEnds.merge(w.getEnd0(), 1, Integer::sum);
      wireEnds.merge(w.getEnd1(), 1, Integer::sum);
    }
    final Map<Location, List<Object[]>> portsAt = new HashMap<>(); // loc -> [component, EndData, portMap]
    final Map<Component, List<Map<String, Object>>> portMaps = new HashMap<>();
    final Map<String, List<Location>> tunnels = new HashMap<>();
    for (final Component c : comps) {
      final List<Map<String, Object>> plist = ports(c, 0, 0);
      portMaps.put(c, plist);
      final List<EndData> ends = c.getEnds();
      for (final Map<String, Object> p : plist) {
        final EndData e = ends.get((Integer) p.get("index"));
        final Location at = e.getLocation();
        nets.find(at);
        portsAt.computeIfAbsent(at, k -> new ArrayList<>()).add(new Object[] {c, e, p});
      }
      if (c.getFactory() instanceof Tunnel) {
        final String l = label(c);
        if (l != null && !ends.isEmpty()) tunnels.computeIfAbsent(l, k -> new ArrayList<>()).add(ends.get(0).getLocation());
      }
    }
    for (final List<Location> group : tunnels.values()) {
      for (int i = 1; i < group.size(); i++) nets.union(group.get(0), group.get(i));
    }

    // group locations by net root and give nets stable ids (ordered by top-left point)
    final Map<Location, List<Location>> members = new HashMap<>();
    for (final Location loc : new ArrayList<>(nets.parent.keySet())) {
      members.computeIfAbsent(nets.find(loc), k -> new ArrayList<>()).add(loc);
    }
    final List<Location> roots = new ArrayList<>(members.keySet());
    final Map<Location, Location> minOf = new HashMap<>();
    for (final Location r : roots) {
      Location best = null;
      for (final Location l : members.get(r)) {
        if (best == null || l.getY() < best.getY() || (l.getY() == best.getY() && l.getX() < best.getX())) best = l;
      }
      minOf.put(r, best);
    }
    roots.sort(Comparator.comparingInt((Location r) -> minOf.get(r).getY()).thenComparingInt(r -> minOf.get(r).getX()));

    final CircuitState state = withValues ? project.getCircuitState(circuit) : null;
    final boolean stateIsLive = state != null && state == project.getCircuitState();

    final Map<Location, String> netIdOf = new HashMap<>();
    final List<Object> netList = new ArrayList<>();
    final List<Object> problems = new ArrayList<>();
    int counter = 0;
    for (final Location root : roots) {
      final List<Location> locs = members.get(root);
      final List<String> drivers = new ArrayList<>();
      final List<String> loads = new ArrayList<>();
      final List<String> bidir = new ArrayList<>();
      final Set<String> names = new java.util.LinkedHashSet<>();
      int wireCount = 0;
      int width = 0;
      for (final Location l : locs) {
        wireCount += wireEnds.getOrDefault(l, 0);
        for (final Object[] entry : portsAt.getOrDefault(l, List.of())) {
          final Component c = (Component) entry[0];
          final EndData e = (EndData) entry[1];
          final Map<String, Object> p = (Map<String, Object>) entry[2];
          final String ref = ids.get(c) + "." + p.get("name");
          width = Math.max(width, e.getWidth().getWidth());
          if (c.getFactory() instanceof Pin || c.getFactory() instanceof Tunnel || c.getFactory() instanceof Clock) {
            final String l2 = label(c);
            if (l2 != null) names.add(l2);
          }
          switch (e.getType()) {
            case EndData.INPUT_ONLY -> loads.add(ref);
            case EndData.OUTPUT_ONLY -> drivers.add(ref);
            default -> bidir.add(ref);
          }
        }
      }
      if (wireCount == 0 && drivers.size() + loads.size() + bidir.size() <= 1) {
        continue; // a lone, unconnected port is reported as a problem below, not as a net
      }
      counter++;
      final String id = "n" + counter;
      for (final Location l : locs) netIdOf.put(l, id);
      final Map<String, Object> n = new LinkedHashMap<>();
      n.put("id", id);
      if (!names.isEmpty()) n.put("names", new ArrayList<>(names));
      if (width == 0) {
        final BitWidth bw = circuit.getWidth(root);
        width = bw == null ? 0 : bw.getWidth();
      }
      n.put("width", width);
      if (!drivers.isEmpty()) n.put("drivers", drivers);
      if (!bidir.isEmpty()) n.put("bidirectional", bidir);
      if (!loads.isEmpty()) n.put("loads", loads);
      n.put("wire_segments", wireCount / 2);
      if (state != null) {
        final Value v = state.getValue(minOf.get(root));
        n.put("value", formatValue(v));
        if (v != null && v.isErrorValue() && stateIsLive) {
          final String who = id + (names.isEmpty() ? "" : " " + names);
          if (drivers.size() + bidir.size() > 1) {
            problems.add(problem("error", "conflict", who + " has conflicting drivers (red wire in Logisim): "
                + drivers, minOf.get(root), List.of(id)));
          } else {
            problems.add(problem("warning", "error_value", who + " carries an error value (red); usually an "
                + "unconnected or floating input upstream of " + drivers, minOf.get(root), List.of(id)));
          }
        }
      }
      final String netName = id + (names.isEmpty() ? "" : " (" + String.join(",", names) + ")");
      if (drivers.isEmpty() && bidir.isEmpty() && !loads.isEmpty()) {
        problems.add(problem("warning", "floating_net", netName + " feeds " + loads + " but nothing drives it",
            minOf.get(root), List.of(id)));
      }
      if (drivers.size() > 1) {
        problems.add(problem("warning", "multiple_drivers", netName + " is driven by " + drivers,
            minOf.get(root), List.of(id)));
      }
      netList.add(n);
    }

    // ---- components
    final List<Object> compList = new ArrayList<>();
    for (final Component c : comps) {
      final Map<String, Object> m = new LinkedHashMap<>();
      m.put("id", ids.get(c));
      final String l = label(c);
      if (l != null) m.put("label", l);
      final String lib = libraryOf(file, c.getFactory(), libCache);
      m.put("library", lib);
      m.put("name", c.getFactory().getName());
      m.put("loc", List.of(c.getLocation().getX(), c.getLocation().getY()));
      final AttributeSet attrs = c.getAttributeSet();
      if (attrs.containsAttribute(StdAttr.FACING)) {
        final Direction d = attrs.getValue(StdAttr.FACING);
        if (d != null) m.put("facing", d.toString());
      }
      if (attrs.containsAttribute(StdAttr.WIDTH)) {
        final BitWidth w = attrs.getValue(StdAttr.WIDTH);
        if (w != null) m.put("width", w.getWidth());
      }
      if (c.getFactory() instanceof Pin) {
        m.put("pin_type", Pin.FACTORY.isInputPin(Instance.getInstanceFor(c)) ? "input" : "output");
      }
      final Bounds b = c.getBounds();
      m.put("bounds", List.of(b.getX(), b.getY(), b.getWidth(), b.getHeight()));
      final Bounds vb = visualBounds(c);
      if (!vb.equals(b)) m.put("visual_bounds", List.of(vb.getX(), vb.getY(), vb.getWidth(), vb.getHeight()));
      final List<Object> plist = new ArrayList<>();
      for (final Map<String, Object> p : portMaps.get(c)) {
        final Map<String, Object> q = new LinkedHashMap<>(p);
        final EndData e = c.getEnds().get((Integer) p.get("index"));
        q.put("x", e.getLocation().getX());
        q.put("y", e.getLocation().getY());
        final String net = netIdOf.get(e.getLocation());
        q.put("net", net);
        plist.add(q);
        if (net == null) {
          final boolean pinDevice = c.getFactory() instanceof Pin;
          // Clear/Preset/Enable style inputs have sensible defaults when left open.
          final String pname = String.valueOf(p.get("name")).toLowerCase(Locale.ROOT);
          final String pdesc = String.valueOf(p.getOrDefault("description", "")).toLowerCase(Locale.ROOT);
          final boolean optional = pname.equals("clear") || pname.equals("preset") || pname.equals("enable")
              || pname.equals("reset") || pdesc.contains("asynchronous");
          final String sev = ("in".equals(p.get("direction")) && !optional) || pinDevice ? "warning" : "info";
          problems.add(problem(sev, "unconnected_port", ids.get(c) + (l == null ? "" : " (" + l + ")")
              + " port " + p.get("name") + " is not connected", e.getLocation(), List.of(ids.get(c))));
        }
      }
      m.put("ports", plist);
      if (withAttributes) {
        final Map<String, Object> props = new TreeMap<>();
        AttributeSet defaults = null;
        try {
          defaults = c.getFactory().createAttributeSet();
        } catch (RuntimeException ignored) {
          defaults = null;
        }
        for (final Attribute<?> a : attrs.getAttributes()) {
          final String now = safeString(a, attrs.getValue((Attribute<Object>) a));
          String def = null;
          if (defaults != null && defaults.containsAttribute(a)) def = safeString(a, defaults.getValue((Attribute<Object>) a));
          if (!Objects.equals(now, def)) props.put(a.getName(), now);
        }
        m.put("properties", props);
      }
      compList.add(m);
    }

    // ---- wires and geometry problems
    final List<Object> wireList = new ArrayList<>();
    for (final Wire w : wires) {
      final Map<String, Object> m = new LinkedHashMap<>();
      m.put("from", List.of(w.getEnd0().getX(), w.getEnd0().getY()));
      m.put("to", List.of(w.getEnd1().getX(), w.getEnd1().getY()));
      m.put("net", netIdOf.get(w.getEnd0()));
      wireList.add(m);
      for (final Location end : List.of(w.getEnd0(), w.getEnd1())) {
        if (wireEnds.getOrDefault(end, 0) == 1 && !portsAt.containsKey(end)) {
          problems.add(problem("warning", "dangling_wire", "wire end " + point(end) + " touches nothing",
              end, List.of(String.valueOf(netIdOf.get(end)))));
        }
      }
      for (final Component c : comps) {
        final Bounds b = c.getBounds();
        if (b.getWidth() < 3 || b.getHeight() < 3) continue;
        if (crossesInterior(w, b)) {
          problems.add(problem("warning", "wire_through_component", "wire " + point(w.getEnd0()) + "-" + point(w.getEnd1())
              + " passes through the body of " + ids.get(c), w.getEnd0(), List.of(ids.get(c))));
        } else {
          final Bounds vb = visualBounds(c);
          if (!vb.equals(b) && crossesInterior(w, vb)) {
            problems.add(problem("info", "wire_over_label", "wire " + point(w.getEnd0()) + "-" + point(w.getEnd1())
                + " runs over the label of " + ids.get(c), w.getEnd0(), List.of(ids.get(c))));
          }
        }
      }
    }
    for (int i = 0; i < comps.size(); i++) {
      for (int j = i + 1; j < comps.size(); j++) {
        final Bounds a = comps.get(i).getBounds();
        final Bounds b = comps.get(j).getBounds();
        if (a.getX() < b.getX() + b.getWidth() && b.getX() < a.getX() + a.getWidth()
            && a.getY() < b.getY() + b.getHeight() && b.getY() < a.getY() + a.getHeight()) {
          problems.add(problem("warning", "overlapping_components", ids.get(comps.get(i)) + " overlaps "
              + ids.get(comps.get(j)), comps.get(i).getLocation(), List.of(ids.get(comps.get(i)), ids.get(comps.get(j)))));
        }
      }
    }
    final Set<WidthIncompatibilityData> incompatible = circuit.getWidthIncompatibilityData();
    for (final WidthIncompatibilityData data : incompatible == null ? Set.<WidthIncompatibilityData>of() : incompatible) {
      final List<String> widths = new ArrayList<>();
      for (int i = 0; i < data.size(); i++) widths.add(point(data.getPoint(i)) + "=" + data.getBitWidth(i).getWidth());
      problems.add(problem("error", "width_mismatch", "incompatible bit widths " + widths,
          data.getPoint(0), List.of(String.valueOf(netIdOf.get(data.getPoint(0))))));
    }
    for (final Map.Entry<String, Integer> e : labelCount.entrySet()) {
      if (e.getValue() > 1) {
        problems.add(problem("info", "duplicate_label", "label \"" + e.getKey() + "\" is used " + e.getValue() + " times",
            null, List.of()));
      }
    }

    final Map<String, Object> result = new LinkedHashMap<>();
    result.put("circuit", circuit.getName());
    final Bounds all = circuit.getBounds();
    result.put("extent", List.of(all.getX(), all.getY(), all.getWidth(), all.getHeight()));
    result.put("components", compList);
    result.put("wires", wireList);
    result.put("nets", netList);
    result.put("problems", problems);
    if (state != null) {
      result.put("values_from", stateIsLive ? "the Logisim window's running simulation" : "a stored simulation state of this circuit");
    }
    return result;
  }

  private static boolean crossesInterior(Wire w, Bounds b) {
    final int x0 = b.getX();
    final int y0 = b.getY();
    final int x1 = b.getX() + b.getWidth();
    final int y1 = b.getY() + b.getHeight();
    final Location a = w.getEnd0();
    final Location c = w.getEnd1();
    if (a.getY() == c.getY()) {
      final int y = a.getY();
      final int lo = Math.min(a.getX(), c.getX());
      final int hi = Math.max(a.getX(), c.getX());
      return y > y0 && y < y1 && lo < x1 - 1 && hi > x0 + 1 && Math.max(lo, x0) + 1 < Math.min(hi, x1) - 1;
    }
    if (a.getX() == c.getX()) {
      final int x = a.getX();
      final int lo = Math.min(a.getY(), c.getY());
      final int hi = Math.max(a.getY(), c.getY());
      return x > x0 && x < x1 && lo < y1 - 1 && hi > y0 + 1 && Math.max(lo, y0) + 1 < Math.min(hi, y1) - 1;
    }
    return false;
  }

  static String point(Location l) {
    return "(" + l.getX() + "," + l.getY() + ")";
  }

  private static Map<String, Object> problem(String severity, String kind, String message, Location at, List<String> refs) {
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("severity", severity);
    m.put("kind", kind);
    m.put("message", message);
    if (at != null) m.put("at", List.of(at.getX(), at.getY()));
    if (refs != null && !refs.isEmpty()) m.put("refs", refs);
    return m;
  }

  // ------------------------------------------------------------------ simulation

  private record PinInfo(Component comp, Instance inst, String label, int width, boolean input) {}

  private static List<PinInfo> pins(Circuit circuit) {
    final List<PinInfo> list = new ArrayList<>();
    for (final Component c : circuit.getNonWires()) {
      if (!(c.getFactory() instanceof Pin)) continue;
      final Instance inst = Instance.getInstanceFor(c);
      final String l = label(c);
      list.add(new PinInfo(c, inst, l, Pin.FACTORY.getWidth(inst).getWidth(), Pin.FACTORY.isInputPin(inst)));
    }
    list.sort(Comparator.comparingInt((PinInfo p) -> p.comp.getLocation().getY()).thenComparingInt(p -> p.comp.getLocation().getX()));
    return list;
  }

  static Value parseValue(Object raw, int width) throws LiveEditor.InvalidOp {
    final BitWidth bw = BitWidth.create(width);
    if (raw instanceof Number n) return Value.createKnown(bw, n.longValue());
    if (raw instanceof Boolean b) return Value.createKnown(bw, b ? 1 : 0);
    String s = String.valueOf(raw).trim().toLowerCase(Locale.ROOT).replace("_", "");
    if (s.equals("x") || s.equals("z") || s.equals("floating")) return Value.createUnknown(bw);
    try {
      if (s.startsWith("0x")) return Value.createKnown(bw, Long.parseUnsignedLong(s.substring(2), 16));
      if (s.startsWith("0b")) return Value.createKnown(bw, Long.parseUnsignedLong(s.substring(2), 2));
      if (s.matches("[01]+") && (s.length() == width || width == 1)) return Value.createKnown(bw, Long.parseUnsignedLong(s, 2));
      return Value.createKnown(bw, Long.parseLong(s));
    } catch (NumberFormatException e) {
      throw new LiveEditor.InvalidOp("cannot read value '" + raw + "' for a " + width + "-bit input");
    }
  }

  /**
   * Evaluates the circuit in a private simulation (the window is untouched). Rows are either given
   * explicitly or generated from all input combinations. Sequential steps can tick the clocks.
   */
  @SuppressWarnings("unchecked")
  static Map<String, Object> simulate(Project project, String circuitName, Map<String, Object> spec) throws LiveEditor.InvalidOp {
    final Circuit circuit = LiveEditor.circuit(project.getLogisimFile(), circuitName);
    final List<PinInfo> all = pins(circuit);
    final Map<String, PinInfo> inputs = new LinkedHashMap<>();
    final Map<String, PinInfo> outputs = new LinkedHashMap<>();
    final List<String> warnings = new ArrayList<>();
    for (final PinInfo p : all) {
      if (p.label == null) {
        warnings.add((p.input ? "input" : "output") + " pin at " + point(p.comp.getLocation()) + " has no label and is ignored");
        continue;
      }
      (p.input ? inputs : outputs).put(p.label, p);
    }
    final boolean sequential = Boolean.TRUE.equals(spec.get("sequential"));
    final boolean resetEachRow = !sequential && Boolean.TRUE.equals(spec.get("reset_each_row"));
    final int cycles = spec.get("clock_cycles") instanceof Number n ? n.intValue() : 0;
    final int maxRows = spec.get("max_rows") instanceof Number n ? Math.min(n.intValue(), 65536) : 1024;

    final List<String> outNames = new ArrayList<>();
    if (spec.get("outputs") instanceof List<?> wanted) {
      for (final Object o : wanted) {
        final String name = String.valueOf(o);
        if (!outputs.containsKey(name) && !inputs.containsKey(name)) {
          throw new LiveEditor.InvalidOp("No pin labelled '" + name + "' in " + circuitName);
        }
        outNames.add(name);
      }
    } else {
      outNames.addAll(outputs.keySet());
    }

    // rows of input assignments
    final List<Map<String, Object>> rows = new ArrayList<>();
    if (spec.get("rows") instanceof List<?> given) {
      for (final Object r : given) rows.add(Json.obj(r));
    } else if (Boolean.TRUE.equals(spec.get("all_combinations"))) {
      final List<String> order = new ArrayList<>();
      if (spec.get("inputs") instanceof List<?> names) {
        for (final Object o : names) order.add(String.valueOf(o));
      } else {
        order.addAll(inputs.keySet());
      }
      int bits = 0;
      for (final String name : order) {
        final PinInfo p = inputs.get(name);
        if (p == null) throw new LiveEditor.InvalidOp("No input pin labelled '" + name + "' in " + circuitName);
        bits += p.width;
      }
      if (bits > 20 || (1L << bits) > maxRows) {
        throw new LiveEditor.InvalidOp("all_combinations needs " + (1L << Math.min(bits, 62)) + " rows (" + bits
            + " input bits); raise max_rows (up to 65536) or list fewer inputs / explicit rows");
      }
      for (long combo = 0; combo < (1L << bits); combo++) {
        final Map<String, Object> row = new LinkedHashMap<>();
        int shift = bits;
        for (final String name : order) {
          final int w = inputs.get(name).width;
          shift -= w;
          row.put(name, (combo >> shift) & ((1L << w) - 1));
        }
        rows.add(row);
      }
    } else if (spec.get("inputs") instanceof Map<?, ?> single) {
      rows.add((Map<String, Object>) single);
    } else {
      rows.add(new LinkedHashMap<>());
    }
    if (rows.size() > maxRows) throw new LiveEditor.InvalidOp(rows.size() + " rows exceed max_rows=" + maxRows);

    // watched points: [x,y] or "compId.port" resolved by the caller into coordinates
    final List<Location> watch = new ArrayList<>();
    final List<String> watchNames = new ArrayList<>();
    if (spec.get("watch") instanceof List<?> ws) {
      for (final Object w : ws) {
        final Map<String, Object> wm = Json.obj(w);
        watch.add(LiveEditor.loc(wm.get("at")));
        watchNames.add(Json.str(wm.get("name")));
      }
    }

    CircuitState state = CircuitState.createRootState(project, circuit, Thread.currentThread());
    Propagator prop = state.getPropagator();
    prop.propagate();
    final List<Object> table = new ArrayList<>();
    boolean anyOscillation = false;
    for (final Map<String, Object> row : rows) {
      if (resetEachRow && !table.isEmpty()) {
        state = CircuitState.createRootState(project, circuit, Thread.currentThread());
        prop = state.getPropagator();
        prop.propagate();
      }
      final Map<String, Object> in = new LinkedHashMap<>();
      for (final Map.Entry<String, Object> e : row.entrySet()) {
        final PinInfo p = inputs.get(e.getKey());
        if (p == null) throw new LiveEditor.InvalidOp("No input pin labelled '" + e.getKey() + "' in " + circuitName);
        final Value v = parseValue(e.getValue(), p.width);
        final InstanceState is = state.getInstanceState(p.comp);
        Pin.FACTORY.driveInputPin(is, v);
        state.markComponentAsDirty(p.comp);
        in.put(e.getKey(), formatValue(v));
      }
      prop.propagate();
      for (int k = 0; k < cycles; k++) {
        prop.toggleClocks();
        prop.propagate();
        prop.toggleClocks();
        prop.propagate();
      }
      final Map<String, Object> out = new LinkedHashMap<>();
      for (final String name : outNames) {
        final PinInfo p = outputs.containsKey(name) ? outputs.get(name) : inputs.get(name);
        out.put(name, formatValue(Pin.FACTORY.getValue(state.getInstanceState(p.comp))));
      }
      final Map<String, Object> r = new LinkedHashMap<>();
      r.put("in", in);
      r.put("out", out);
      if (!watch.isEmpty()) {
        final Map<String, Object> seen = new LinkedHashMap<>();
        for (int i = 0; i < watch.size(); i++) seen.put(watchNames.get(i), formatValue(state.getValue(watch.get(i))));
        r.put("watch", seen);
      }
      if (prop.isOscillating()) {
        r.put("oscillating", true);
        anyOscillation = true;
      }
      table.add(r);
    }
    final Map<String, Object> result = new LinkedHashMap<>();
    result.put("circuit", circuit.getName());
    result.put("inputs", new ArrayList<>(inputs.keySet()));
    result.put("outputs", outNames);
    result.put("rows", table);
    if (anyOscillation) result.put("oscillation", true);
    if (!warnings.isEmpty()) result.put("warnings", warnings);
    result.put("note", "values: 0/1 per bit, x = floating (blue), E = conflict (red)");
    return result;
  }

  /** Drives input pins in the window's own simulation so the user sees the values. */
  static Map<String, Object> drive(Project project, String circuitName, Map<String, Object> values) throws LiveEditor.InvalidOp {
    final Circuit circuit = LiveEditor.circuit(project.getLogisimFile(), circuitName);
    if (project.getCurrentCircuit() != circuit) project.setCurrentCircuit(circuit);
    final CircuitState state = project.getCircuitState();
    final Map<String, PinInfo> inputs = new HashMap<>();
    for (final PinInfo p : pins(circuit)) if (p.input && p.label != null) inputs.put(p.label, p);
    final Map<String, Object> set = new LinkedHashMap<>();
    for (final Map.Entry<String, Object> e : values.entrySet()) {
      final PinInfo p = inputs.get(e.getKey());
      if (p == null) throw new LiveEditor.InvalidOp("No input pin labelled '" + e.getKey() + "' in " + circuitName);
      final Value v = parseValue(e.getValue(), p.width);
      Pin.FACTORY.driveInputPin(state.getInstanceState(p.comp), v);
      state.markComponentAsDirty(p.comp);
      set.put(e.getKey(), formatValue(v));
    }
    project.getSimulator().nudge();
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("set", set);
    return m;
  }
}
