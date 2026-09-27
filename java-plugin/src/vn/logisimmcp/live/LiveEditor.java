package vn.logisimmcp.live;

import com.cburch.logisim.circuit.Circuit;
import com.cburch.logisim.circuit.CircuitAttributes;
import com.cburch.logisim.circuit.CircuitMutation;
import com.cburch.logisim.circuit.SubcircuitFactory;
import com.cburch.logisim.circuit.Wire;
import com.cburch.logisim.comp.Component;
import com.cburch.logisim.comp.ComponentFactory;
import com.cburch.logisim.data.Attribute;
import com.cburch.logisim.data.AttributeSet;
import com.cburch.logisim.data.Bounds;
import com.cburch.logisim.data.Location;
import com.cburch.logisim.file.LogisimFile;
import com.cburch.logisim.file.LogisimFileActions;
import com.cburch.logisim.fpga.designrulecheck.CorrectLabel;
import com.cburch.logisim.gui.main.Canvas;
import com.cburch.logisim.instance.StdAttr;
import com.cburch.logisim.prefs.AppPreferences;
import com.cburch.logisim.proj.Action;
import com.cburch.logisim.proj.Project;
import com.cburch.logisim.proj.ProjectEvent;
import com.cburch.logisim.proj.ProjectListener;
import com.cburch.logisim.std.wiring.Pin;
import com.cburch.logisim.std.wiring.ProbeAttributes;
import com.cburch.logisim.tools.AddTool;
import com.cburch.logisim.tools.Library;
import com.cburch.logisim.tools.Tool;
import com.cburch.logisim.util.StringGetter;
import com.cburch.logisim.util.SyntaxChecker;
import java.awt.Rectangle;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;
import java.util.WeakHashMap;
import javax.swing.SwingUtilities;

/**
 * Applies bridge edits to the live Logisim model as ordinary, undoable Logisim actions, and
 * checks that the running window and the saved file agree. Every method runs on the EDT.
 */
final class LiveEditor {
  private LiveEditor() {}

  /** An edit Logisim itself rejects; nothing is left applied when this is thrown. */
  static final class InvalidOp extends Exception {
    InvalidOp(String message) {
      super(message);
    }
  }

  /** The window changed (a hand edit, undo or redo) since the bridge last looked. */
  static final class Stale extends Exception {
    final long external;

    Stale(long external) {
      super("stale");
      this.external = external;
    }
  }

  // ------------------------------------------------------------------ change tracking

  /** Counts model changes and which of them were not made by the bridge. */
  static final class Tracker implements ProjectListener {
    long revision;
    long external;

    @Override
    public void projectChanged(ProjectEvent event) {
      switch (event.getAction()) {
        case ProjectEvent.ACTION_COMPLETE,
            ProjectEvent.UNDO_COMPLETE,
            ProjectEvent.REDO_COMPLETE,
            ProjectEvent.ACTION_MERGE,
            ProjectEvent.ACTION_SET_FILE -> {
          revision++;
          if (!internal) external++;
        }
        default -> {
          // selection, tool, repaint and simulation events are not edits
        }
      }
    }
  }

  private static final Map<Project, Tracker> TRACKERS = new WeakHashMap<>();
  /** True while the bridge itself is changing a project (EDT only). */
  static boolean internal;

  static Tracker track(Project project) {
    return TRACKERS.computeIfAbsent(
        project,
        p -> {
          final Tracker t = new Tracker();
          p.addProjectListener(t);
          return t;
        });
  }

  static Map<String, Object> status(Project project) {
    final Tracker t = track(project);
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("open_in_app", true);
    m.put("dirty", project.isFileDirty());
    m.put("revision", t.revision);
    m.put("external_revision", t.external);
    final Circuit current = project.getCurrentCircuit();
    m.put("current_circuit", current == null ? null : current.getName());
    return m;
  }

  // ------------------------------------------------------------------ resolution helpers

  static Library libraryByDesc(LogisimFile file, String desc) {
    if (desc == null || desc.isEmpty()) return file; // subcircuits live in the file itself
    for (final Library lib : file.getLibraries()) {
      if (desc.equals(file.getLoader().getDescriptor(lib))) return lib;
    }
    if (desc.startsWith("#")) {
      for (final Library lib : file.getLibraries()) {
        if (desc.substring(1).equals(lib.getName())) return lib;
      }
    }
    return null;
  }

  static Tool findTool(Library lib, String name) {
    final Tool tool = lib.getTool(name);
    if (tool != null) return tool;
    for (final Library sub : lib.getLibraries()) {
      final Tool found = findTool(sub, name);
      if (found != null) return found;
    }
    return null;
  }

  static ComponentFactory factory(LogisimFile file, String desc, String name) throws InvalidOp {
    final Library lib = libraryByDesc(file, desc);
    if (lib == null) {
      throw new InvalidOp("Library " + desc + " is not loaded in this Logisim project");
    }
    final Tool tool = findTool(lib, name);
    if (!(tool instanceof AddTool addTool)) {
      throw new InvalidOp(
          (desc == null || desc.isEmpty() ? "Circuit" : "Component")
              + " '"
              + name
              + "' does not exist"
              + (desc == null || desc.isEmpty() ? " in this project" : " in library " + desc));
    }
    return addTool.getFactory();
  }

  static Location loc(Object value) {
    final List<Object> xy = Json.arr(value);
    return Location.create(Json.integer(xy.get(0)), Json.integer(xy.get(1)), false);
  }

  static Map<String, String> props(Object value) {
    final Map<String, String> result = new LinkedHashMap<>();
    if (value == null) return result;
    for (final Map.Entry<String, Object> e : Json.obj(value).entrySet()) {
      result.put(e.getKey(), Json.str(e.getValue()));
    }
    return result;
  }

  /** Builds attributes exactly the way XmlReader.initAttributeSet does for a loaded file. */
  @SuppressWarnings("unchecked")
  static AttributeSet buildAttrs(
      ComponentFactory factory, Map<String, String> props, List<String> warnings, String what)
      throws InvalidOp {
    final AttributeSet attrs = factory.createAttributeSet();
    final Set<String> used = new HashSet<>();
    for (int i = 0; true; i++) {
      final List<Attribute<?>> list = attrs.getAttributes(); // may grow (e.g. Splitter)
      if (i >= list.size()) break;
      final Attribute<Object> attr = (Attribute<Object>) list.get(i);
      final String value = props.get(attr.getName());
      if (value != null) {
        used.add(attr.getName());
        try {
          attrs.setValue(attr, attr.parse(value));
        } catch (RuntimeException e) {
          throw new InvalidOp(
              "Invalid value '" + value + "' for property '" + attr.getName() + "' of " + what);
        }
      } else if (attr.equals(ProbeAttributes.PROBEAPPEARANCE)) {
        attrs.setValue(ProbeAttributes.PROBEAPPEARANCE, StdAttr.APPEAR_CLASSIC);
      } else if (attr.equals(StdAttr.APPEARANCE)) {
        attrs.setValue(StdAttr.APPEARANCE, StdAttr.APPEAR_EVOLUTION);
      }
    }
    for (final String key : props.keySet()) {
      if (!used.contains(key)) {
        warnings.add(
            what + ": '" + key + "' is not a Logisim property of this component and is ignored");
      }
    }
    return attrs;
  }

  static String describe(String name, Location loc) {
    return name + " at (" + loc.getX() + "," + loc.getY() + ")";
  }

  static String validateCircuitName(LogisimFile file, String name, Circuit renaming)
      throws InvalidOp {
    if (name == null || name.isBlank()) throw new InvalidOp("Circuit name must not be empty");
    final String hdl = AppPreferences.HdlType.get();
    if (CorrectLabel.isKeyword(name, hdl, false)) {
      throw new InvalidOp("\"" + name + "\" is a reserved " + hdl + " keyword");
    }
    final String message = SyntaxChecker.getErrorMessage(name, hdl);
    if (message != null) throw new InvalidOp("\"" + name + "\" is not a valid circuit name: " + message);
    for (final Circuit other : file.getCircuits()) {
      if (other != renaming && SyntaxChecker.namesEqual(other.getName(), name, hdl)) {
        throw new InvalidOp("A circuit named \"" + name + "\" already exists");
      }
    }
    if (renaming != null) {
      for (final Component comp : renaming.getNonWires()) {
        if (comp.getFactory() instanceof Pin) {
          final String label = comp.getAttributeSet().getValue(StdAttr.LABEL);
          if (label != null && !label.isEmpty() && SyntaxChecker.namesEqual(label, name, hdl)) {
            throw new InvalidOp("A pin in the circuit is already labelled \"" + name + "\"");
          }
        }
      }
    }
    return name;
  }

  static Circuit circuit(LogisimFile file, String name) throws InvalidOp {
    final Circuit circuit = file.getCircuit(name);
    if (circuit == null) throw new InvalidOp("Circuit not found in Logisim: " + name);
    return circuit;
  }

  static StringGetter label(String text) {
    return new StringGetter() {
      @Override
      public String toString() {
        return text;
      }
    };
  }

  // ------------------------------------------------------------------ wires

  private record Seg(int x1, int y1, int x2, int y2) {
    static Seg of(int ax, int ay, int bx, int by) {
      // canonical order: left-to-right, then top-to-bottom
      if (ax < bx || (ax == bx && ay <= by)) return new Seg(ax, ay, bx, by);
      return new Seg(bx, by, ax, ay);
    }

    static Seg of(Wire w) {
      return of(w.getEnd0().getX(), w.getEnd0().getY(), w.getEnd1().getX(), w.getEnd1().getY());
    }

    boolean horizontal() {
      return y1 == y2;
    }

    boolean vertical() {
      return x1 == x2;
    }

    /** Positive-length collinear overlap. */
    boolean overlaps(Seg o) {
      if (horizontal() && o.horizontal() && y1 == o.y1 && !vertical() && !o.vertical()) {
        return Math.max(x1, o.x1) < Math.min(x2, o.x2);
      }
      if (vertical() && o.vertical() && x1 == o.x1 && !horizontal() && !o.horizontal()) {
        return Math.max(y1, o.y1) < Math.min(y2, o.y2);
      }
      return false;
    }

    /** This segment minus {@code cut}; both collinear and overlapping. */
    List<Seg> minus(Seg cut) {
      final List<Seg> pieces = new ArrayList<>(2);
      if (horizontal()) {
        if (x1 < cut.x1) pieces.add(of(x1, y1, cut.x1, y1));
        if (cut.x2 < x2) pieces.add(of(cut.x2, y1, x2, y1));
      } else {
        if (y1 < cut.y1) pieces.add(of(x1, y1, x1, cut.y1));
        if (cut.y2 < y2) pieces.add(of(x1, cut.y2, x1, y2));
      }
      return pieces;
    }

    Wire toWire() {
      return Wire.create(Location.create(x1, y1, false), Location.create(x2, y2, false));
    }

    List<Integer> json() {
      return List.of(x1, y1, x2, y2);
    }
  }

  static Seg seg(Object value) {
    final List<Object> v = Json.arr(value);
    return Seg.of(
        Json.integer(v.get(0)), Json.integer(v.get(1)), Json.integer(v.get(2)), Json.integer(v.get(3)));
  }

  /** Merges touching/overlapping collinear segments so split and merged wires compare equal. */
  static Set<Seg> normalize(Iterable<Seg> input) {
    final Map<Integer, List<int[]>> rows = new HashMap<>();
    final Map<Integer, List<int[]>> cols = new HashMap<>();
    final Set<Seg> other = new HashSet<>();
    for (final Seg s : input) {
      if (s.horizontal() && !s.vertical()) {
        rows.computeIfAbsent(s.y1, k -> new ArrayList<>()).add(new int[] {s.x1, s.x2});
      } else if (s.vertical() && !s.horizontal()) {
        cols.computeIfAbsent(s.x1, k -> new ArrayList<>()).add(new int[] {s.y1, s.y2});
      } else if (!(s.horizontal() && s.vertical())) {
        other.add(s); // diagonal; Logisim does not create these but keep them comparable
      }
    }
    final Set<Seg> result = new HashSet<>(other);
    for (final Map.Entry<Integer, List<int[]>> e : rows.entrySet()) {
      for (final int[] span : merge(e.getValue())) result.add(Seg.of(span[0], e.getKey(), span[1], e.getKey()));
    }
    for (final Map.Entry<Integer, List<int[]>> e : cols.entrySet()) {
      for (final int[] span : merge(e.getValue())) result.add(Seg.of(e.getKey(), span[0], e.getKey(), span[1]));
    }
    return result;
  }

  private static List<int[]> merge(List<int[]> spans) {
    spans.sort((a, b) -> Integer.compare(a[0], b[0]));
    final List<int[]> out = new ArrayList<>();
    for (final int[] s : spans) {
      if (!out.isEmpty() && s[0] <= out.get(out.size() - 1)[1]) {
        final int[] last = out.get(out.size() - 1);
        last[1] = Math.max(last[1], s[1]);
      } else {
        out.add(new int[] {s[0], s[1]});
      }
    }
    return out;
  }

  // ------------------------------------------------------------------ APPLY

  /**
   * Applies an ordered list of operations. Each operation becomes one Logisim action, so the
   * user can undo it with Ctrl+Z. If any operation is rejected, the ones already applied are
   * undone again and nothing changes.
   */
  static Map<String, Object> apply(
      Project project, List<Object> ops, String actionLabel, long expectedExternal)
      throws InvalidOp, Stale {
    final Tracker tracker = track(project);
    if (expectedExternal >= 0 && tracker.external != expectedExternal) {
      throw new Stale(tracker.external);
    }
    final List<String> warnings = new ArrayList<>();
    final List<Bounds> touched = new ArrayList<>();
    Circuit focus = null;
    int applied = 0;
    internal = true;
    try {
      for (final Object rawOp : ops) {
        final Map<String, Object> op = Json.obj(rawOp);
        final String kind = Json.str(op.get("op"));
        final LogisimFile file = project.getLogisimFile();
        final Action action;
        switch (kind == null ? "" : kind) {
          case "edit" -> {
            final Circuit circuit = circuit(file, Json.str(op.get("circuit")));
            action = buildEdit(project, circuit, op, actionLabel, warnings, touched);
            focus = circuit;
          }
          case "add_circuit" -> {
            final String name = validateCircuitName(file, Json.str(op.get("name")), null);
            final Circuit created = new Circuit(name, file, project);
            action = LogisimFileActions.addCircuit(created);
            focus = created;
          }
          case "rename_circuit" -> {
            final Circuit circuit = circuit(file, Json.str(op.get("from")));
            final String to = validateCircuitName(file, Json.str(op.get("to")), circuit);
            final CircuitMutation mutation = new CircuitMutation(circuit);
            mutation.setForCircuit(CircuitAttributes.NAME_ATTR, to);
            action = mutation.toAction(label(actionLabel));
            focus = circuit;
          }
          case "remove_circuit" -> {
            final Circuit circuit = circuit(file, Json.str(op.get("name")));
            if (file.getCircuits().size() <= 1) {
              throw new InvalidOp("A Logisim project must keep at least one circuit");
            }
            if (!project.getDependencies().canRemove(circuit)) {
              throw new InvalidOp("Circuit " + circuit.getName() + " is still used as a subcircuit");
            }
            if (project.getCurrentCircuit() == circuit) {
              for (final Circuit other : file.getCircuits()) {
                if (other != circuit) {
                  project.setCurrentCircuit(other);
                  break;
                }
              }
            }
            if (focus == circuit) focus = null;
            action = LogisimFileActions.removeCircuit(circuit);
          }
          case "set_main" -> {
            final Circuit circuit = circuit(file, Json.str(op.get("name")));
            action = file.getMainCircuit() == circuit ? null : LogisimFileActions.setMainCircuit(circuit);
          }
          default -> throw new InvalidOp("Unknown live operation: " + kind);
        }
        if (action != null) {
          project.doAction(action);
          applied++;
        }
      }
    } catch (InvalidOp | RuntimeException e) {
      for (int i = 0; i < applied; i++) project.undoAction();
      if (e instanceof InvalidOp invalid) throw invalid;
      throw new IllegalStateException("Logisim rejected the edit: " + e, e);
    } finally {
      internal = false;
    }
    if (focus != null && project.getLogisimFile().getCircuits().contains(focus)) {
      if (project.getCurrentCircuit() != focus) project.setCurrentCircuit(focus);
      revealLater(project, touched);
    }
    final Map<String, Object> result = status(project);
    result.put("applied_actions", applied);
    result.put("warnings", warnings);
    return result;
  }

  private static Component findComponent(
      Circuit circuit, ComponentFactory factory, Location at, Map<String, String> props, Set<Component> taken) {
    Component best = null;
    int bestScore = -1;
    for (final Component comp : circuit.getNonWires()) {
      if (taken.contains(comp) || !comp.getLocation().equals(at) || !sameFactory(comp.getFactory(), factory)) continue;
      final int score = matchScore(comp, props);
      if (score > bestScore) {
        best = comp;
        bestScore = score;
      }
    }
    return best;
  }

  /** Factories are usually singletons; compare names too so reloaded libraries still match. */
  static boolean sameFactory(ComponentFactory a, ComponentFactory b) {
    if (a == b) return true;
    return a != null && b != null && a.getClass() == b.getClass() && Objects.equals(a.getName(), b.getName());
  }

  @SuppressWarnings("unchecked")
  private static int matchScore(Component comp, Map<String, String> props) {
    int score = 0;
    final AttributeSet attrs = comp.getAttributeSet();
    for (final Map.Entry<String, String> e : props.entrySet()) {
      final Attribute<Object> attr = (Attribute<Object>) attrs.getAttribute(e.getKey());
      if (attr == null) continue;
      try {
        if (Objects.equals(
            attr.toStandardString(attrs.getValue(attr)), attr.toStandardString(attr.parse(e.getValue())))) {
          score++;
        }
      } catch (RuntimeException ignored) {
        // unparsable value never matches
      }
    }
    return score;
  }

  private record CompSpec(
      String lib, String name, Location loc, Map<String, String> props, ComponentFactory factory) {}

  private static CompSpec spec(LogisimFile file, Object raw) throws InvalidOp {
    final Map<String, Object> c = Json.obj(raw);
    final String lib = Json.str(c.get("lib"));
    final String name = Json.str(c.get("name"));
    return new CompSpec(lib, name, loc(c.get("loc")), props(c.get("props")), factory(file, lib, name));
  }

  @SuppressWarnings("unchecked")
  private static Action buildEdit(
      Project project,
      Circuit circuit,
      Map<String, Object> op,
      String actionLabel,
      List<String> warnings,
      List<Bounds> touched)
      throws InvalidOp {
    final LogisimFile file = project.getLogisimFile();
    final List<CompSpec> removals = new ArrayList<>();
    for (final Object raw : Json.arr(op.get("remove_components"))) removals.add(spec(file, raw));
    final List<CompSpec> additions = new ArrayList<>();
    for (final Object raw : Json.arr(op.get("add_components"))) additions.add(spec(file, raw));

    final CircuitMutation mutation = new CircuitMutation(circuit);
    final Set<Component> taken = new HashSet<>();

    // A removal and an addition of the same device at the same place is a property change:
    // edit it in place so the device keeps its identity (and its simulation state).
    final List<CompSpec> pendingAdds = new ArrayList<>(additions);
    for (final CompSpec removed : removals) {
      final Component existing = findComponent(circuit, removed.factory, removed.loc, removed.props, taken);
      if (existing == null) {
        warnings.add(describe(removed.name, removed.loc) + " was not found in the Logisim window");
        continue;
      }
      taken.add(existing);
      CompSpec replacement = null;
      for (final CompSpec add : pendingAdds) {
        if (sameFactory(add.factory, removed.factory) && add.loc.equals(removed.loc)) {
          replacement = add;
          break;
        }
      }
      if (replacement == null) {
        mutation.remove(existing);
        continue;
      }
      pendingAdds.remove(replacement);
      final AttributeSet target =
          buildAttrs(replacement.factory, replacement.props, warnings, describe(replacement.name, replacement.loc));
      final AttributeSet current = existing.getAttributeSet();
      if (sameAttributeNames(current, target)) {
        for (final Attribute<?> a : target.getAttributes()) {
          final Attribute<Object> attr = (Attribute<Object>) a;
          final Object want = target.getValue(attr);
          if (!Objects.equals(current.getValue(attr), want)) mutation.set(existing, attr, want);
        }
      } else {
        mutation.replace(existing, replacement.factory.createComponent(replacement.loc, target));
      }
      touched.add(existing.getBounds());
    }
    for (final CompSpec add : pendingAdds) {
      final AttributeSet attrs = buildAttrs(add.factory, add.props, warnings, describe(add.name, add.loc));
      final Component comp;
      try {
        comp = add.factory.createComponent(add.loc, attrs);
      } catch (RuntimeException e) {
        throw new InvalidOp("Logisim could not create " + describe(add.name, add.loc) + ": " + e.getMessage());
      }
      mutation.add(comp);
      touched.add(comp.getBounds());
    }

    // Wires: Logisim merges and splits segments on its own, so work on geometry.
    final List<Seg> removeSegs = new ArrayList<>();
    for (final Object raw : Json.arr(op.get("remove_wires"))) removeSegs.add(seg(raw));
    if (!removeSegs.isEmpty()) {
      final Map<Seg, Wire> original = new HashMap<>();
      for (final Wire w : circuit.getWires()) original.put(Seg.of(w), w);
      List<Seg> working = new ArrayList<>(original.keySet());
      for (final Seg cut : removeSegs) {
        final List<Seg> next = new ArrayList<>();
        boolean hit = false;
        for (final Seg s : working) {
          if (s.overlaps(cut)) {
            hit = true;
            next.addAll(s.minus(cut));
          } else {
            next.add(s);
          }
        }
        if (!hit) warnings.add("wire " + cut.json() + " was not found in the Logisim window");
        working = next;
      }
      final Set<Seg> kept = new HashSet<>(working);
      for (final Map.Entry<Seg, Wire> e : original.entrySet()) {
        if (!kept.contains(e.getKey())) {
          mutation.remove(e.getValue());
        }
      }
      for (final Seg s : kept) {
        if (!original.containsKey(s)) mutation.add(s.toWire());
      }
    }
    for (final Object raw : Json.arr(op.get("add_wires"))) {
      final Seg s = seg(raw);
      if (s.x1 == s.x2 && s.y1 == s.y2) throw new InvalidOp("A wire must have two different endpoints");
      final Wire w = s.toWire();
      mutation.add(w);
      touched.add(w.getBounds());
    }
    if (mutation.isEmpty()) return null;
    return mutation.toAction(label(actionLabel));
  }

  private static boolean sameAttributeNames(AttributeSet a, AttributeSet b) {
    final List<Attribute<?>> la = a.getAttributes();
    final List<Attribute<?>> lb = b.getAttributes();
    if (la.size() != lb.size()) return false;
    for (int i = 0; i < la.size(); i++) {
      if (!la.get(i).equals(lb.get(i))) return false;
    }
    return true;
  }

  /** Scrolls the canvas just enough to show what changed, after Swing has laid it out. */
  static void revealLater(Project project, List<Bounds> touched) {
    if (touched.isEmpty() || project.getFrame() == null) return;
    Bounds all = null;
    for (final Bounds b : touched) {
      if (b == null || b == Bounds.EMPTY_BOUNDS) continue;
      all = all == null ? b : all.add(b);
    }
    if (all == null) return;
    final Bounds target = all.expand(20);
    SwingUtilities.invokeLater(
        () -> {
          final Canvas canvas = project.getFrame().getCanvas();
          if (canvas == null || canvas.getCanvasPane() == null) return;
          canvas.recomputeSize();
          final double zoom = canvas.getCanvasPane().getZoomFactor();
          final Rectangle rect =
              new Rectangle(
                  (int) Math.floor(Math.max(0, target.getX()) * zoom),
                  (int) Math.floor(Math.max(0, target.getY()) * zoom),
                  (int) Math.ceil(target.getWidth() * zoom),
                  (int) Math.ceil(target.getHeight() * zoom));
          // Only move the view when the new work is completely off screen; partial overlap
          // means the user can already see it and a jump would feel jittery.
          final Rectangle visible = canvas.getVisibleRect();
          if (!visible.intersects(rect)) {
            if (rect.width > visible.width || rect.height > visible.height) {
              rect.setSize(Math.min(rect.width, visible.width), Math.min(rect.height, visible.height));
            }
            canvas.scrollRectToVisible(rect);
          }
        });
  }

  // ------------------------------------------------------------------ EXPORT / VERIFY

  /** Writes the window's current model with Logisim's own writer, without saving the project. */
  static void export(Project project, File dest, File mainFile) throws IOException {
    final LogisimFile file = project.getLogisimFile();
    try (OutputStream out = new FileOutputStream(dest)) {
      file.write(out, file.getLoader(), mainFile);
    }
  }

  /**
   * Compares the window with the state the bridge just saved. When they agree the project is
   * marked clean (as if Logisim had saved it) and its stale autosave is removed.
   */
  @SuppressWarnings("unchecked")
  static Map<String, Object> verifyAndMarkClean(Project project, Map<String, Object> expected, File mainFile) {
    final LogisimFile file = project.getLogisimFile();
    final List<String> mismatches = new ArrayList<>();
    final Set<String> expectedNames = new TreeSet<>();
    for (final Object rawCircuit : Json.arr(expected.get("circuits"))) {
      final Map<String, Object> ec = Json.obj(rawCircuit);
      final String name = Json.str(ec.get("name"));
      expectedNames.add(name);
      final Circuit circuit = file.getCircuit(name);
      if (circuit == null) {
        mismatches.add("circuit " + name + " is missing in the window");
        continue;
      }
      final Set<Component> taken = new HashSet<>();
      for (final Object raw : Json.arr(ec.get("components"))) {
        final Map<String, Object> c = Json.obj(raw);
        final String cname = Json.str(c.get("name"));
        final Location at = loc(c.get("loc"));
        ComponentFactory factory;
        try {
          factory = factory(file, Json.str(c.get("lib")), cname);
        } catch (InvalidOp e) {
          mismatches.add(name + ": " + e.getMessage());
          continue;
        }
        final Map<String, String> p = props(c.get("props"));
        final Component comp = findComponent(circuit, factory, at, p, taken);
        if (comp == null) {
          mismatches.add(name + ": " + describe(cname, at) + " is missing in the window");
          continue;
        }
        taken.add(comp);
        final AttributeSet attrs = comp.getAttributeSet();
        for (final Map.Entry<String, String> e : p.entrySet()) {
          final Attribute<Object> attr = (Attribute<Object>) attrs.getAttribute(e.getKey());
          if (attr == null) continue; // ignored by Logisim on load as well
          try {
            final String want = attr.toStandardString(attr.parse(e.getValue()));
            final String have = attr.toStandardString(attrs.getValue(attr));
            if (!Objects.equals(want, have)) {
              mismatches.add(name + ": " + describe(cname, at) + " has " + e.getKey() + "=" + have + ", file has " + want);
            }
          } catch (RuntimeException ex) {
            mismatches.add(name + ": " + describe(cname, at) + " has an unreadable " + e.getKey());
          }
        }
      }
      for (final Component comp : circuit.getNonWires()) {
        if (!taken.contains(comp)) {
          mismatches.add(name + ": extra " + describe(comp.getFactory().getName(), comp.getLocation()) + " in the window");
        }
      }
      final List<Seg> fileWires = new ArrayList<>();
      for (final Object raw : Json.arr(ec.get("wires"))) fileWires.add(seg(raw));
      final List<Seg> appWires = new ArrayList<>();
      for (final Wire w : circuit.getWires()) appWires.add(Seg.of(w));
      final Set<Seg> a = normalize(fileWires);
      final Set<Seg> b = normalize(appWires);
      if (!a.equals(b)) {
        final Set<Seg> onlyFile = new HashSet<>(a);
        onlyFile.removeAll(b);
        final Set<Seg> onlyApp = new HashSet<>(b);
        onlyApp.removeAll(a);
        mismatches.add(name + ": wires differ (file only " + onlyFile.size() + ", window only " + onlyApp.size() + ")");
      }
      if (mismatches.size() > 25) break;
    }
    for (final Circuit c : file.getCircuits()) {
      if (!expectedNames.contains(c.getName())) mismatches.add("extra circuit " + c.getName() + " in the window");
    }
    final String main = Json.str(expected.get("main"));
    if (main != null && (file.getMainCircuit() == null || !main.equals(file.getMainCircuit().getName()))) {
      mismatches.add("main circuit differs");
    }

    final Map<String, Object> result = new LinkedHashMap<>();
    result.put("verified", mismatches.isEmpty());
    result.put("mismatches", mismatches.size() > 25 ? mismatches.subList(0, 25) : mismatches);
    if (mismatches.isEmpty()) {
      internal = true;
      try {
        project.setFileAsClean();
      } finally {
        internal = false;
      }
      file.getLoader().deleteAutosave();
      final File autosave = LiveAgent.namedAutosaveFor(mainFile);
      if (autosave.isFile() && !autosave.delete()) autosave.deleteOnExit();
    }
    result.putAll(status(project));
    return result;
  }

  static Map<String, Object> show(Project project, String circuitName) throws InvalidOp {
    if (circuitName != null && !circuitName.isEmpty()) {
      final Circuit circuit = circuit(project.getLogisimFile(), circuitName);
      if (project.getCurrentCircuit() != circuit) project.setCurrentCircuit(circuit);
    }
    return status(project);
  }

  static boolean isSubcircuit(ComponentFactory factory) {
    return factory instanceof SubcircuitFactory;
  }
}
