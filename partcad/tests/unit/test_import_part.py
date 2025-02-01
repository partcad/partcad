import pytest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from partcad.actions.part_actions import import_part_action


@pytest.fixture
def mock_project():
    """Creates a mock project with add_part and update_part_config methods."""
    project = MagicMock()
    project.path = "/mock/project"
    project.name = "TestProject"
    return project


@patch("shutil.copy")
@patch("shutil.copystat")
@patch("partcad.actions.part_actions.deep_copy_metadata")
@patch("pathlib.Path.exists", return_value=True)  # Mock file existence
def test_import_part_success(mock_exists, mock_copy_metadata, mock_copystat, mock_copy, mock_project):
    """Tests successful part import without conversion."""
    source_path = "/mock/source/part.step"
    target_path = "/mock/project/part.step"

    import_part_action(mock_project, "step", "part", source_path)

    # Ensure file is copied
    mock_copy.assert_called_once_with(Path(source_path), Path(target_path))

    # Ensure metadata is copied
    mock_copy_metadata.assert_called_once_with(Path(source_path), Path(target_path))

    # Ensure part is added to the project
    mock_project.add_part.assert_called_once_with("step", str(target_path), {})

    # Ensure project config is updated
    mock_project.update_part_config.assert_called_once_with("part", {"path": str(target_path)})


@patch("shutil.copy")
@patch("shutil.copystat")
@patch("partcad.actions.part_actions.deep_copy_metadata")
@patch("partcad.actions.part_actions.convert_part_action")
@patch("pathlib.Path.exists", return_value=True)  # Mock file existence
def test_import_part_with_conversion(mock_exists, mock_convert, mock_copy_metadata, mock_copystat, mock_copy, mock_project):
    """Tests part import with format conversion."""
    source_path = "/mock/source/part.step"
    target_path = "/mock/project/part.step"

    import_part_action(mock_project, "step", "part", source_path, target_format="stl")

    # Ensure file is copied
    mock_copy.assert_called_once_with(Path(source_path), Path(target_path))

    # Ensure conversion is triggered
    mock_convert.assert_called_once_with(mock_project, "part", "stl", in_place=True)

    # Ensure metadata is copied
    mock_copy_metadata.assert_called_once_with(Path(source_path), Path(target_path))

    # Ensure part is added to the project
    mock_project.add_part.assert_called_once_with("step", str(target_path), {})

    # Ensure project config is updated
    mock_project.update_part_config.assert_called_once_with("part", {"path": str(target_path)})


@patch("shutil.copy")
def test_import_part_missing_source(mock_copy, mock_project):
    """Tests behavior when the source file is missing."""
    source_path = "/mock/source/missing.step"

    with pytest.raises(ValueError, match="Source file '/mock/source/missing.step' does not exist."):
        import_part_action(mock_project, "step", "part", source_path)

    # Ensure no copy attempt was made
    mock_copy.assert_not_called()


@patch("shutil.copy", side_effect=shutil.Error("Copy failed"))  # Simulate copy failure
@patch("pathlib.Path.exists", return_value=True)  # Mock file existence
def test_import_part_copy_error(mock_exists, mock_copy, mock_project):
    """Tests handling of file copy failure."""
    source_path = "/mock/source/part.step"

    with pytest.raises(ValueError, match="Failed to copy file from"):
        import_part_action(mock_project, "step", "part", source_path)

    # Ensure copy was attempted
    mock_copy.assert_called_once()
