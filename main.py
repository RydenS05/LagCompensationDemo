import pygame
import threading
import time
import math
import random
from collections import deque

WIDTH, HEIGHT = 1000, 700
PANEL_W = WIDTH // 2
SLIDER_AREA = 80
PANEL_H = (HEIGHT - SLIDER_AREA) // 2

FPS = 60
TICK_RATE = 20
SEND_RATE = 20
BALL_RADIUS = 24

DARK_GRAY  = (30,  30,  30)
PANEL_BG   = (20,  20,  40)
SERVER_COL = (100, 200, 255)
NOCOMP_COL = (220, 80,  80)
DR_COL     = (230, 200, 50)
FIX_COL    = (80,  200, 120)

# ── SHARED SERVER STATE ───────────────────────────────────────────────────────
server_pos = [PANEL_W // 2, PANEL_H // 2]
server_vel = [6.0, 4.5]

# ── PACKET QUEUE & CLIENT STATE ───────────────────────────────────────────────
packet_queue = deque()
pending_packets = deque()
latency_ms = 0
packet_loss_pct = 0
packets_sent = 0
packets_lost = 0

nocomp_pos = [PANEL_W // 2, PANEL_H // 2]

dr_pos = [PANEL_W // 2, PANEL_H // 2]
dr_vel = [0.0, 0.0]
dr_last_time = time.time()

fix_pos = [PANEL_W // 2, PANEL_H // 2]
fix_vel = [0.0, 0.0]
fix_blend_start = [PANEL_W // 2, PANEL_H // 2]
fix_blend_target = [PANEL_W // 2, PANEL_H // 2]
fix_blending = False
fix_blend_timer = 0.0
BLEND_DURATION = 0.25     # seconds to smooth the correction over
DIVERGE_THRESHOLD = 15    # pixels — how wrong the prediction must be before blending

def server_loop():
    global server_pos, server_vel

    tick_interval = 1.0 / TICK_RATE
    send_interval = 1.0 / SEND_RATE
    last_tick = time.time()
    last_send = time.time()
    last_vchange = time.time()

    while True:
        now = time.time()

        if now - last_tick >= tick_interval:
            last_tick = now

            server_pos[0] += server_vel[0]
            server_pos[1] += server_vel[1]

            if server_pos[0] <= BALL_RADIUS or server_pos[0] >= PANEL_W - BALL_RADIUS:
                server_vel[0] *= -1
            if server_pos[1] <= BALL_RADIUS or server_pos[1] >= PANEL_H - BALL_RADIUS:
                server_vel[1] *= -1

            if now - last_vchange > random.uniform(2.0, 4.0):
                speed = random.uniform(5, 9)
                angle = random.uniform(0, 2 * math.pi)
                server_vel[0] = speed * math.cos(angle)
                server_vel[1] = speed * math.sin(angle)
                last_vchange = now

        if now - last_send >= send_interval:
            last_send = now
            packet_queue.append((time.time(), server_pos[0], server_pos[1], server_vel[0], server_vel[1]))

        time.sleep(0.001)


def client_receive_loop():
    global nocomp_pos, dr_pos, dr_vel, dr_last_time
    global fix_pos, fix_vel, fix_blend_start, fix_blend_target, fix_blending, fix_blend_timer
    global packets_sent, packets_lost

    while True:
        now = time.time()

        while packet_queue:
            pkt = packet_queue.popleft()
            packets_sent += 1
            
            # Randomly drop packet based on loss percentage
            if random.randint(0, 100) < packet_loss_pct:
                packets_lost += 1
                continue    # drop it — never gets delivered to any client
            
            deliver_at = now + (latency_ms / 1000.0)
            pending_packets.append((deliver_at, pkt))

        while pending_packets and pending_packets[0][0] <= now:
            _, pkt = pending_packets.popleft()
            ts, px, py, pvx, pvy = pkt

            # No compensation
            nocomp_pos[0] = px
            nocomp_pos[1] = py

            # Dead reckoning
            dr_pos[0] = px
            dr_pos[1] = py
            dr_vel[0] = pvx
            dr_vel[1] = pvy
            dr_last_time = now

            # DR + correction — check how wrong our prediction was
            error = math.hypot(fix_pos[0] - px, fix_pos[1] - py)
            fix_vel[0] = pvx
            fix_vel[1] = pvy

            if error > DIVERGE_THRESHOLD:
                # Prediction was too wrong — blend smoothly to correct position
                fix_blend_start[0] = fix_pos[0]
                fix_blend_start[1] = fix_pos[1]
                fix_blend_target[0] = px
                fix_blend_target[1] = py
                fix_blending = True
                fix_blend_timer = 0.0
            else:
                # Prediction was close enough — just snap, difference is invisible
                fix_pos[0] = px
                fix_pos[1] = py

        time.sleep(0.001)


def main():
    global fix_blending, fix_blend_timer, fix_pos, fix_vel, dr_pos, dr_vel
    global latency_ms, packet_loss_pct

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Lag Compensation Demo")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Consolas", 15, bold=True)
    small_font = pygame.font.SysFont("Consolas", 12)

    threading.Thread(target=server_loop, daemon=True).start()
    threading.Thread(target=client_receive_loop, daemon=True).start()

    panels = [
        (0,       0,       SERVER_COL, "SERVER — Ground Truth"),
        (PANEL_W, 0,       NOCOMP_COL, "CLIENT — No Compensation"),
        (0,       PANEL_H, DR_COL,     "CLIENT — Dead Reckoning"),
        (PANEL_W, PANEL_H, FIX_COL,    "CLIENT — DR + Correction"),
    ]

    # Slider definitions
    # Latency slider — left half of bottom bar
    LAT_SLIDER_X = 80
    LAT_SLIDER_Y = PANEL_H * 2 + 25
    LAT_SLIDER_W = (WIDTH // 2) - 100
    MAX_LATENCY  = 500

    # Packet loss slider — right half of bottom bar
    LOSS_SLIDER_X = (WIDTH // 2) + 80
    LOSS_SLIDER_Y = PANEL_H * 2 + 25
    LOSS_SLIDER_W = (WIDTH // 2) - 100
    MAX_LOSS      = 80   # cap at 80% — above that it's basically unplayable

    lat_dragging  = False
    loss_dragging = False

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

            # Mouse button down — check if either slider handle was clicked
            if event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos

                lat_handle_x = LAT_SLIDER_X + int((latency_ms / MAX_LATENCY) * LAT_SLIDER_W)
                if abs(mx - lat_handle_x) <= 12 and abs(my - LAT_SLIDER_Y) <= 12:
                    lat_dragging = True

                loss_handle_x = LOSS_SLIDER_X + int((packet_loss_pct / MAX_LOSS) * LOSS_SLIDER_W)
                if abs(mx - loss_handle_x) <= 12 and abs(my - LOSS_SLIDER_Y) <= 12:
                    loss_dragging = True

            if event.type == pygame.MOUSEBUTTONUP:
                lat_dragging  = False
                loss_dragging = False

            if event.type == pygame.MOUSEMOTION:
                mx, my = event.pos
                if lat_dragging:
                    clamped = max(LAT_SLIDER_X, min(mx, LAT_SLIDER_X + LAT_SLIDER_W))
                    latency_ms = int(((clamped - LAT_SLIDER_X) / LAT_SLIDER_W) * MAX_LATENCY)
                if loss_dragging:
                    clamped = max(LOSS_SLIDER_X, min(mx, LOSS_SLIDER_X + LOSS_SLIDER_W))
                    packet_loss_pct = int(((clamped - LOSS_SLIDER_X) / LOSS_SLIDER_W) * MAX_LOSS)

        # ── UPDATE ────────────────────────────────────────────────────────────
        dt = clock.get_time() / 1000.0

        # Dead reckoning prediction
        dr_pos[0] += dr_vel[0] * dt * TICK_RATE
        dr_pos[1] += dr_vel[1] * dt * TICK_RATE
        dr_pos[0] = max(BALL_RADIUS, min(dr_pos[0], PANEL_W - BALL_RADIUS))
        dr_pos[1] = max(BALL_RADIUS, min(dr_pos[1], PANEL_H - BALL_RADIUS))

        # DR + correction prediction
        if fix_blending:
            fix_blend_timer += dt
            t = min(fix_blend_timer / BLEND_DURATION, 1.0)
            fix_pos[0] = fix_blend_start[0] + (fix_blend_target[0] - fix_blend_start[0]) * t
            fix_pos[1] = fix_blend_start[1] + (fix_blend_target[1] - fix_blend_start[1]) * t
            if t >= 1.0:
                fix_blending = False
        else:
            fix_pos[0] += fix_vel[0] * dt * TICK_RATE
            fix_pos[1] += fix_vel[1] * dt * TICK_RATE
        fix_pos[0] = max(BALL_RADIUS, min(fix_pos[0], PANEL_W - BALL_RADIUS))
        fix_pos[1] = max(BALL_RADIUS, min(fix_pos[1], PANEL_H - BALL_RADIUS))

        # ── DRAW ──────────────────────────────────────────────────────────────
        screen.fill(DARK_GRAY)

        # Panels
        for (px, py, color, label) in panels:
            pygame.draw.rect(screen, PANEL_BG, (px, py, PANEL_W, PANEL_H))
            pygame.draw.rect(screen, color, (px, py, PANEL_W, PANEL_H), 3)
            label_surf = font.render(label, True, color)
            screen.blit(label_surf, (px + 10, py + 10))

        # Grid dividers
        pygame.draw.line(screen, DARK_GRAY, (PANEL_W, 0), (PANEL_W, PANEL_H * 2), 3)
        pygame.draw.line(screen, DARK_GRAY, (0, PANEL_H), (WIDTH, PANEL_H), 3)

        # Balls
        pygame.draw.circle(screen, SERVER_COL, (int(server_pos[0]), int(server_pos[1])), BALL_RADIUS)
        pygame.draw.circle(screen, (255, 255, 255), (int(server_pos[0]), int(server_pos[1])), BALL_RADIUS, 2)

        pygame.draw.circle(screen, NOCOMP_COL, (int(nocomp_pos[0]) + PANEL_W, int(nocomp_pos[1])), BALL_RADIUS)
        pygame.draw.circle(screen, (255, 255, 255), (int(nocomp_pos[0]) + PANEL_W, int(nocomp_pos[1])), BALL_RADIUS, 2)

        pygame.draw.circle(screen, DR_COL, (int(dr_pos[0]), int(dr_pos[1]) + PANEL_H), BALL_RADIUS)
        pygame.draw.circle(screen, (255, 255, 255), (int(dr_pos[0]), int(dr_pos[1]) + PANEL_H), BALL_RADIUS, 2)

        pygame.draw.circle(screen, FIX_COL, (int(fix_pos[0]) + PANEL_W, int(fix_pos[1]) + PANEL_H), BALL_RADIUS)
        pygame.draw.circle(screen, (255, 255, 255), (int(fix_pos[0]) + PANEL_W, int(fix_pos[1]) + PANEL_H), BALL_RADIUS, 2)

        # ── SLIDER AREA ───────────────────────────────────────────────────────
        pygame.draw.rect(screen, (15, 15, 30), (0, PANEL_H * 2, WIDTH, SLIDER_AREA))

        # Latency slider
        pygame.draw.rect(screen, (60, 60, 80), (LAT_SLIDER_X, LAT_SLIDER_Y - 4, LAT_SLIDER_W, 8), border_radius=4)
        lat_fill = int((latency_ms / MAX_LATENCY) * LAT_SLIDER_W)
        pygame.draw.rect(screen, SERVER_COL, (LAT_SLIDER_X, LAT_SLIDER_Y - 4, lat_fill, 8), border_radius=4)
        lat_handle_x = LAT_SLIDER_X + lat_fill
        pygame.draw.circle(screen, (255, 255, 255), (lat_handle_x, LAT_SLIDER_Y), 10)
        pygame.draw.circle(screen, SERVER_COL, (lat_handle_x, LAT_SLIDER_Y), 7)

        lat_label = small_font.render(f"Latency: {latency_ms}ms", True, (200, 200, 200))
        screen.blit(lat_label, (LAT_SLIDER_X, LAT_SLIDER_Y - 20))

        # Packet loss slider
        pygame.draw.rect(screen, (60, 60, 80), (LOSS_SLIDER_X, LOSS_SLIDER_Y - 4, LOSS_SLIDER_W, 8), border_radius=4)
        loss_fill = int((packet_loss_pct / MAX_LOSS) * LOSS_SLIDER_W)
        pygame.draw.rect(screen, NOCOMP_COL, (LOSS_SLIDER_X, LOSS_SLIDER_Y - 4, loss_fill, 8), border_radius=4)
        loss_handle_x = LOSS_SLIDER_X + loss_fill
        pygame.draw.circle(screen, (255, 255, 255), (loss_handle_x, LOSS_SLIDER_Y), 10)
        pygame.draw.circle(screen, NOCOMP_COL, (loss_handle_x, LOSS_SLIDER_Y), 7)

        loss_label = small_font.render(f"Packet Loss: {packet_loss_pct}%", True, (200, 200, 200))
        screen.blit(loss_label, (LOSS_SLIDER_X, LOSS_SLIDER_Y - 20))

        # Stats readout
        loss_pct = (packets_lost / packets_sent * 100) if packets_sent > 0 else 0
        stats = small_font.render(
            f"Packets Sent: {packets_sent}    Dropped: {packets_lost}    Actual Loss: {loss_pct:.1f}%",
            True, (150, 150, 150)
        )
        screen.blit(stats, (WIDTH // 2 - stats.get_width() // 2, PANEL_H * 2 + 55))

        pygame.display.flip()
        clock.tick(FPS)

if __name__ == "__main__":
    main()