package vn.logisimmcp.live;

import com.cburch.logisim.circuit.Circuit;
import com.cburch.logisim.circuit.CircuitState;
import com.cburch.logisim.circuit.Simulator;
import com.cburch.logisim.comp.Component;
import com.cburch.logisim.comp.ComponentDrawContext;
import com.cburch.logisim.data.Bounds;
import com.cburch.logisim.data.Value;
import com.cburch.logisim.gui.chrono.ChronoPanel;
import com.cburch.logisim.gui.chrono.LeftPanel;
import com.cburch.logisim.gui.generic.TikZWriter;
import com.cburch.logisim.gui.log.ComponentSelector;
import com.cburch.logisim.gui.log.LogFrame;
import com.cburch.logisim.gui.log.LoggableContract;
import com.cburch.logisim.gui.log.Model;
import com.cburch.logisim.gui.log.SignalInfo;
import com.cburch.logisim.gui.main.ExportImage;
import com.cburch.logisim.proj.Project;
import java.awt.Color;
import java.awt.Container;
import java.awt.Dimension;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
import javax.imageio.ImageIO;
import javax.swing.JTabbedPane;
import javax.swing.SwingUtilities;
import javax.swing.table.JTableHeader;

/**
 * Images drawn by Logisim itself: a circuit exactly as File &gt; Export Image draws it, and the
 * Timing diagram window (Simulate &gt; Timing diagram) after driving the window's own simulation.
 */
final class LiveRender {
  private static final int BORDER = 5;
  private static final long WAIT_MS = 10_000;

  private LiveRender() {}

  // ---------------------------------------------------------------- circuit image

  /** Same drawing as Logisim's ExportImage, without its dialogs. Runs on the Swing thread. */
  static Map<String, Object> image(
      Project project, String circuitName, File dest, String format, double scale, boolean printerView)
      throws LiveEditor.InvalidOp {
    final Circuit circuit = LiveEditor.circuit(project.getLogisimFile(), circuitName);
    final String kind = format.toLowerCase(Locale.ROOT);
    if (!List.of("png", "gif", "jpg", "jpeg", "svg").contains(kind)) {
      throw new LiveEditor.InvalidOp("format must be png, gif, jpg or svg");
    }
    if (scale <= 0 || scale > 16) throw new LiveEditor.InvalidOp("scale must be between 0 and 16");
    final var frame = project.getFrame();
    if (frame == null) throw new LiveEditor.InvalidOp("the project has no Logisim window");
    final var canvas = frame.getCanvas();
    Graphics probe = canvas.getGraphics();
    if (probe == null) probe = new BufferedImage(1, 1, BufferedImage.TYPE_INT_RGB).getGraphics();
    final Bounds raw = circuit.getBounds(probe);
    if (raw == null || raw.getWidth() <= 0 || raw.getHeight() <= 0) {
      throw new LiveEditor.InvalidOp("circuit " + circuit.getName() + " is empty, nothing to draw");
    }
    final Bounds bds = raw.expand(BORDER);
    final int width = (int) Math.round(bds.getWidth() * scale);
    final int height = (int) Math.round(bds.getHeight() * scale);
    final boolean vector = kind.equals("svg");
    final BufferedImage img = vector ? null : new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
    final Graphics base = vector ? new TikZWriter() : img.getGraphics();
    if (base instanceof TikZWriter tz) tz.setSvgMode(true);
    final Graphics g = base.create();
    try {
      if (!printerView || !vector) {
        g.setColor(printerView ? Color.WHITE : canvas.getBackground());
        g.fillRect(0, 0, width, height);
      }
      g.setColor(Color.BLACK);
      if (!(g instanceof Graphics2D g2)) throw new LiveEditor.InvalidOp("cannot create image graphics");
      g2.scale(scale, scale);
      g2.translate(-bds.getX(), -bds.getY());
      final CircuitState state = project.getCircuitState(circuit);
      circuit.draw(new ComponentDrawContext(canvas, circuit, state, base, g, printerView), null);
      final File parent = dest.getAbsoluteFile().getParentFile();
      if (parent != null) parent.mkdirs();
      try {
        if (vector) {
          ((TikZWriter) g).writeSvg(width, height, dest);
        } else {
          ImageIO.write(img, kind.equals("jpg") || kind.equals("jpeg") ? "JPEG" : kind.toUpperCase(Locale.ROOT), dest);
        }
      } catch (Exception e) {
        throw new LiveEditor.InvalidOp("could not write " + dest + ": " + e);
      }
    } finally {
      g.dispose();
    }
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("circuit", circuit.getName());
    m.put("width", width);
    m.put("height", height);
    m.put("bytes", dest.length());
    return m;
  }

  // ---------------------------------------------------------------- timing diagram

  /**
   * Drives the window's own simulation step by step while Logisim's Timing diagram window
   * records it, then exports that window's picture. Runs on a worker thread: each step waits for
   * the simulator thread, the Swing work is done with invokeAndWait.
   */
  @SuppressWarnings("unchecked")
  static Map<String, Object> timing(Project project, Map<String, Object> args) throws Exception {
    final String circuitName = Json.str(args.get("circuit"));
    final File dest = new File(Json.str(args.get("dest")));
    final String format = String.valueOf(args.getOrDefault("format", "png")).toLowerCase(Locale.ROOT);
    final int fmt = switch (format) {
      case "png" -> ExportImage.FORMAT_PNG;
      case "gif" -> ExportImage.FORMAT_GIF;
      case "jpg", "jpeg" -> ExportImage.FORMAT_JPG;
      case "svg" -> ExportImage.FORMAT_SVG;
      default -> throw new LiveEditor.InvalidOp("format must be png, gif, jpg or svg");
    };
    final boolean reset = !Boolean.FALSE.equals(args.get("reset"));
    final boolean show = !Boolean.FALSE.equals(args.get("show"));
    final List<String> wanted = new ArrayList<>();
    if (args.get("signals") instanceof List<?> names) for (final Object o : names) wanted.add(String.valueOf(o));
    final List<Map<String, Object>> steps = new ArrayList<>();
    if (args.get("steps") instanceof List<?> given) for (final Object s : given) steps.add(Json.obj(s));

    final Simulator sim = project.getSimulator();
    if (sim == null) throw new LiveEditor.InvalidOp("the project has no simulator");
    final AtomicLong completed = new AtomicLong();
    final AtomicLong resets = new AtomicLong();
    final Simulator.Listener listener =
        new Simulator.Listener() {
          @Override
          public void simulatorReset(Simulator.Event e) {
            resets.incrementAndGet();
          }

          @Override
          public void simulatorStateChanged(Simulator.Event e) {}

          @Override
          public void propagationCompleted(Simulator.Event e) {
            completed.incrementAndGet();
          }
        };

    final Circuit circuit = edt(() -> {
      final Circuit c = LiveEditor.circuit(project.getLogisimFile(), circuitName);
      if (project.getCurrentCircuit() != c) project.setCurrentCircuit(c);
      return c;
    });
    if (!sim.isAutoPropagating()) {
      throw new LiveEditor.InvalidOp("Simulate > Auto-Propagate is off in the Logisim window; turn it on first");
    }
    int totalTicks = 0;
    for (final Map<String, Object> step : steps) totalTicks += ticksOf(step);
    final List<SignalInfo> clocks = edt(() -> ComponentSelector.findClocks(circuit));
    if (totalTicks > 0 && (clocks == null || clocks.isEmpty())) {
      throw new LiveEditor.InvalidOp("circuit " + circuit.getName() + " has no Clock component to tick");
    }
    if (totalTicks > 4000) throw new LiveEditor.InvalidOp("at most 4000 clock ticks per recording");

    sim.addSimulatorListener(listener);
    try {
      if (reset) {
        final long r = resets.get();
        final long c = completed.get();
        sim.reset();
        waitFor(() -> resets.get() > r && completed.get() > c, "the simulation reset");
      }
      final LogFrame frame = edt(() -> {
        final LogFrame f = project.getLogFrame();
        if (show) f.setVisible(true);
        return f;
      });
      final List<SignalInfo> shown = edt(() -> configureSignals(project, circuit, frame.getModel(), wanted));
      final List<Object> table = new ArrayList<>();
      table.add(sample(project, shown, "start"));
      int index = 0;
      for (final Map<String, Object> step : steps) {
        index++;
        if (step.get("set") instanceof Map<?, ?> set && !set.isEmpty()) {
          edt(() -> {
            LiveInspector.driveWindow(project, circuit, (Map<String, Object>) set);
            return null;
          });
          final long c = completed.get();
          if (sim.nudge()) waitFor(() -> completed.get() > c, "propagation after step " + index);
        }
        final int ticks = ticksOf(step);
        for (int t = 0; t < ticks; t++) {
          final long c = completed.get();
          sim.tick(1);
          waitFor(() -> completed.get() > c, "clock tick in step " + index);
        }
        table.add(sample(project, shown, step.get("label") != null ? String.valueOf(step.get("label")) : "step " + index));
      }

      final AtomicReference<String> problem = new AtomicReference<>();
      edt(() -> {
        final ChronoPanel chrono = find(frame.getContentPane(), ChronoPanel.class);
        if (chrono == null) {
          problem.set("the Timing diagram panel was not found");
          return null;
        }
        if (show) {
          final JTabbedPane tabs = find(frame.getContentPane(), JTabbedPane.class);
          if (tabs != null) tabs.setSelectedComponent(chrono);
        }
        chrono.revalidate();
        return null;
      });
      if (problem.get() != null) throw new LiveEditor.InvalidOp(problem.get());
      final File parent = dest.getAbsoluteFile().getParentFile();
      if (parent != null) parent.mkdirs();
      final long before = dest.isFile() ? dest.lastModified() : -1;
      if (dest.isFile()) dest.delete();
      edt(() -> {
        // queued model events reach the panel first, then it is drawn to the file
        final ChronoPanel chrono = find(frame.getContentPane(), ChronoPanel.class);
        layOut(frame, chrono);
        chrono.getPrintHandler().exportImage(dest, fmt);
        return null;
      });
      if (!dest.isFile() || dest.length() == 0) {
        throw new LiveEditor.InvalidOp("Logisim could not write the timing diagram to " + dest);
      }
      final Map<String, Object> m = new LinkedHashMap<>();
      m.put("circuit", circuit.getName());
      final List<Object> names = new ArrayList<>();
      for (final SignalInfo s : shown) names.add(s.getShortName());
      m.put("signals", names);
      m.put("samples", table);
      m.put("ticks", totalTicks);
      m.put("bytes", dest.length());
      m.put("replaced_existing", before >= 0);
      return m;
    } finally {
      sim.removeSimulatorListener(listener);
    }
  }

  /**
   * The export prints the signal table at its current size. A window that was just opened (or
   * never shown) has not been laid out yet, which would print empty, truncated name columns.
   */
  private static void layOut(LogFrame frame, ChronoPanel chrono) {
    frame.validate();
    final LeftPanel left = chrono.getLeftPanel();
    final Dimension pref = left.getPreferredSize();
    if (left.getWidth() < pref.width || left.getHeight() < pref.height) {
      left.setSize(Math.max(left.getWidth(), pref.width), Math.max(left.getHeight(), pref.height));
      left.doLayout();
    }
    final JTableHeader header = left.getTableHeader();
    if (header != null && header.getWidth() < left.getWidth()) {
      header.setSize(left.getWidth(), ChronoPanel.HEADER_HEIGHT);
      header.doLayout();
    }
  }

  private static int ticksOf(Map<String, Object> step) throws LiveEditor.InvalidOp {
    int ticks = 0;
    if (step.get("clock_cycles") instanceof Number n) ticks += 2 * n.intValue();
    if (step.get("half_ticks") instanceof Number n) ticks += n.intValue();
    if (ticks < 0) throw new LiveEditor.InvalidOp("clock_cycles and half_ticks cannot be negative");
    return ticks;
  }

  /** Puts exactly the requested signals, in order, into the timing model. */
  private static List<SignalInfo> configureSignals(
      Project project, Circuit circuit, Model model, List<String> wanted) throws LiveEditor.InvalidOp {
    if (model == null || model.getCircuitState() != project.getCircuitState()) {
      throw new LiveEditor.InvalidOp("the Timing diagram is not following circuit " + circuit.getName());
    }
    final List<SignalInfo> current = new ArrayList<>();
    for (int i = 0; i < model.getSignalCount(); i++) current.add(model.getItem(i));
    if (wanted.isEmpty()) return current;
    final List<SignalInfo> desired = new ArrayList<>();
    for (final String label : wanted) {
      SignalInfo found = null;
      for (final SignalInfo s : current) {
        if (s.getDepth() == 1 && label.equals(LiveInspector.label(s.getComponent()))) found = s;
      }
      if (found == null) {
        final Component comp = byLabel(circuit, label);
        found = new SignalInfo(circuit, new Component[] {comp}, null);
      }
      if (!desired.contains(found)) desired.add(found);
    }
    final List<SignalInfo> extra = new ArrayList<>(current);
    extra.removeAll(desired);
    if (!extra.isEmpty()) model.remove(extra);
    // One at a time: Model.addOrMove does not advance its index past an item that is already in
    // place, so a batch call would insert the next items above it.
    for (int k = 0; k < desired.size(); k++) model.addOrMove(List.of(desired.get(k)), k);
    model.simulatorReset(); // start the picture from the current state
    return desired;
  }

  private static Component byLabel(Circuit circuit, String label) throws LiveEditor.InvalidOp {
    final List<String> known = new ArrayList<>();
    for (final Component c : circuit.getNonWires()) {
      final String l = LiveInspector.label(c);
      if (l == null || c.getFeature(LoggableContract.class) == null) continue;
      if (l.equals(label)) return c;
      known.add(l);
    }
    known.sort(String::compareTo);
    throw new LiveEditor.InvalidOp(
        "No loggable component labelled '" + label + "' in " + circuit.getName()
            + "; labelled signals: " + (known.isEmpty() ? "none" : String.join(", ", known)));
  }

  private static Map<String, Object> sample(Project project, List<SignalInfo> shown, String label) throws Exception {
    return edt(() -> {
      final CircuitState state = project.getCircuitState();
      final Map<String, Object> values = new LinkedHashMap<>();
      for (final SignalInfo s : shown) {
        final Value v = s.fetchValue(state);
        values.put(s.getShortName(), v == null ? "x" : LiveInspector.formatValue(v));
      }
      final Map<String, Object> row = new LinkedHashMap<>();
      row.put("at", label);
      row.put("values", values);
      return row;
    });
  }

  @SuppressWarnings("unchecked")
  private static <T> T find(java.awt.Component root, Class<T> type) {
    if (type.isInstance(root)) return (T) root;
    if (root instanceof Container c) {
      for (final java.awt.Component child : c.getComponents()) {
        final T hit = find(child, type);
        if (hit != null) return hit;
      }
    }
    return null;
  }

  private static void waitFor(BooleanSupplier done, String what) throws LiveEditor.InvalidOp {
    final long deadline = System.currentTimeMillis() + WAIT_MS;
    while (!done.getAsBoolean()) {
      if (System.currentTimeMillis() > deadline) {
        throw new LiveEditor.InvalidOp("timed out waiting for " + what + " in the Logisim window");
      }
      try {
        Thread.sleep(2);
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        throw new LiveEditor.InvalidOp("interrupted while waiting for " + what);
      }
    }
  }

  static <T> T edt(Callable<T> body) throws Exception {
    if (SwingUtilities.isEventDispatchThread()) return body.call();
    final AtomicReference<T> result = new AtomicReference<>();
    final AtomicReference<Exception> failure = new AtomicReference<>();
    SwingUtilities.invokeAndWait(() -> {
      try {
        result.set(body.call());
      } catch (Exception e) {
        failure.set(e);
      }
    });
    if (failure.get() != null) throw failure.get();
    return result.get();
  }
}
