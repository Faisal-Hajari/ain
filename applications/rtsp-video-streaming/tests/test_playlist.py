from rtsp_video_streaming.playlist import Playlist, normalize_extensions


def make_files(root, names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def test_normalize_extensions_strips_dots_and_case():
    assert normalize_extensions([".MP4", "mkv", " .AvI ", ""]) == ["mp4", "mkv", "avi"]


def test_scan_filters_by_extension_and_sorts(tmp_path):
    make_files(tmp_path, ["b.mp4", "a.mkv", "notes.txt", "c.MP4"])
    playlist = Playlist(tmp_path, extensions=["mp4", "mkv"])
    assert [p.name for p in playlist.scan()] == ["a.mkv", "b.mp4", "c.MP4"]


def test_scan_ignores_subfolders_unless_recursive(tmp_path):
    make_files(tmp_path, ["a.mp4", "sub/b.mp4"])
    assert [p.name for p in Playlist(tmp_path).scan()] == ["a.mp4"]
    assert [p.name for p in Playlist(tmp_path, recursive=True).scan()] == ["a.mp4", "b.mp4"]


def test_scan_picks_up_files_added_later(tmp_path):
    playlist = Playlist(tmp_path)
    assert playlist.scan() == []
    make_files(tmp_path, ["new.mp4"])
    assert [p.name for p in playlist.scan()] == ["new.mp4"]


def test_scan_of_missing_folder_is_empty(tmp_path):
    assert Playlist(tmp_path / "gone").scan() == []


def test_shuffle_is_seeded_and_keeps_the_same_set(tmp_path):
    names = [f"{i:02d}.mp4" for i in range(10)]
    make_files(tmp_path, names)
    first = Playlist(tmp_path, shuffle=True, seed=7).scan()
    second = Playlist(tmp_path, shuffle=True, seed=7).scan()
    assert first == second
    assert sorted(p.name for p in first) == names
