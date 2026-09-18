"""ליגה אירופית: ערוצי מועדונים שאומתו שמעלים תקצירים (18.9.26), ולא נוער/עתודה."""
import main

CC = main.LEAGUES["uel"]["club_channels"]
VERIFIED = {
    "Anderlecht": "UCIr5bpTRrkwJprfaG1owIZw",
    "Celta Vigo": "UCCJLVZYqRb_85b2Flpg04cg",
    "Real Sociedad": "UCfeqewEKWQ8CXY8OiXoMxxw",
    "Sturm Graz": "UCcReHK9o6bc5NT2cj4mpJKQ",
    "Marseille": "UCoKweTwEeA-D9vuSVw_Z_DQ",
    "AZ Alkmaar": "UCTCO3NaW_heI8H6U7f43Now",
    "NEC Nijmegen": "UCF4UEYKNui8ytU9vC9h58fg",
    "Red Bull Salzburg": "UCNXjAsLzro7bnZVWqnnkgsg",
    "Rennes": "UC96bdUrtQVEqx_OmKwFAgXg",
    "Sparta Prague": "UCJcXzTZcKukYq9O4ZBtVxdw",
    "Viktoria Plzeň": "UCemUcP3Rwmz6d9yrW1Vn3tw",
    "Union Saint-Gilloise": "UCk9RAl0uUwjYbTaFQMFaX5g",
    "Bayer Leverkusen": "UCSMZmPVql528Cph9WPvt0GA",
}


def test_czech_and_uel_titles_from_the_new_channels():
    ok = lambda title, home, away, club: main.is_match_highlight(
        title, home, away, None, None, False, club)
    # ספרטה פראג כותבים "SESTŘIH" — וזה משחק הליגה האירופית שלהן
    assert ok("Ararat-Armenia 1:4 Sparta | Dvougólový Guddal řídil vítězství | SESTŘIH",
              "Ararat-Armenia", "Sparta Prague", "Sparta Prague")
    assert ok("Highlights | UEL - J1 | SK Sturm Graz / Stade Rennais F.C. (0-0)",
              "Sturm Graz", "Rennes", "Rennes")
    assert ok("Salzburg v Austria Vienna | Highlights | Matchday 6",
              "Red Bull Salzburg", "Austria Vienna", "Red Bull Salzburg")


def test_verified_channels_are_configured():
    for team, cid in VERIFIED.items():
        assert CC[team] == cid, team


def test_channels_without_highlights_are_not_configured():
    """נבדקו ידנית ואין בהם תקצירים — רק ראיונות ומסיבות עיתונאים."""
    for team in ("Dinamo Zagreb", "Olympiacos", "Ferencváros", "Lyon", "Beşiktaş",
                 "Hapoel Be'er Sheva", "Juventus", "Lech Poznań", "Hoffenheim",
                 "Ararat-Armenia", "Celje", "Jagiellonia Białystok", "Levski Sofia",
                 "Lillestrøm", "OFI Crete", "Omonia Nicosia", "Torreense"):
        assert team not in CC, team


def test_real_uel_highlight_titles_are_matched():
    ok = lambda title, home, away, club: main.is_match_highlight(
        title, home, away, None, None, False, club)
    assert ok("HIGHLIGHTS | Europa League 26-27 | J1 | Real Sociedad 1 - 2 AFC Bournemouth",
              "Real Sociedad", "Bournemouth", "Real Sociedad")
    assert ok("UEFA Europa League Highlights: SK Sturm Graz vs. Stade Rennais F.C. | Matchday 1",
              "Sturm Graz", "Rennes", "Sturm Graz")
    assert ok("AC Omonia Nicosia vs Celta (1-0) | Highlights & goal | UEFA Europa League 26/27",
              "Omonia Nicosia", "Celta Vigo", "Celta Vigo")
    assert ok("HIGHLIGHTS: RSC Anderlecht - Olympique Lyonnais | 2026-2027",
              "Anderlecht", "Lyon", "Anderlecht")


def test_youth_and_reserve_highlights_are_rejected():
    """באותם ערוצים עולים גם תקצירי נוער — באותם ימים."""
    for title, club in [("HIGHLIGHTS U23: RSCA Futures - KSC Lokeren | 2026-2027", "Anderlecht"),
                        ("ALL the Actions from Cittadella-Juventus Next Gen | Highlights - Serie C",
                         "Juventus"),
                        ("Keutgen's goal IS NOT ENOUGH | Juventus U20 1-2 Albinoleffe | Highlights Primavera 1",
                         "Juventus")]:
        assert not main.is_match_highlight(title, club, "Some Opponent", None, None, False, club), title
