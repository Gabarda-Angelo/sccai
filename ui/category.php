<!-- category.php (POS component) -->

<?php
include_once 'connectdb.php';
session_start();
include_once "header.php"; 
if (!isset($_SESSION['email']) || $_SESSION['role'] === 'Cashier') { 
    echo "<script>
            alert('Sorry, you can\'t access this. Please contact the Admin.');
            window.location.href = '../index.php';
          </script>"; 
    exit;
}


// Handle new category insertion
if (isset($_POST['btnsave'])) {
    $category = trim($_POST['txtcategory']);
    if (empty($category)) {
        $_SESSION['status'] = "Category field is empty";
        $_SESSION['status_code'] = "warning";
    } else {
        $insert = $pdo->prepare("INSERT INTO categories (category_name) VALUES (:cat)");
        $insert->bindParam(':cat', $category);

        if ($insert->execute()) {
            $_SESSION['status'] = "Category added successfully";
            $_SESSION['status_code'] = "success";
        } else {
            $_SESSION['status'] = "Category add failed";
            $_SESSION['status_code'] = "warning";
        }
    }
}

// Handle category update
if (isset($_POST['btnupdate'])) {
    $category = trim($_POST['txtcategory']);
    $id = $_POST['txtcatid'];
    if (empty($category)) {
        $_SESSION['status'] = "Category field is empty";
        $_SESSION['status_code'] = "warning";
    } else {
        $update = $pdo->prepare("UPDATE categories SET category_name = :cat WHERE category_id = :id");
        $update->bindParam(':cat', $category);
        $update->bindParam(':id', $id);

        if ($update->execute()) {
            $_SESSION['status'] = "Category updated successfully";
            $_SESSION['status_code'] = "success";
        } else {
            $_SESSION['status'] = "Category update failed";
            $_SESSION['status_code'] = "warning";
        }
    }
}

// Handle category deletion
if (isset($_POST['btndelete'])) {
    $delete = $pdo->prepare("DELETE FROM categories WHERE category_id = :id");
    $delete->bindParam(':id', $_POST['btndelete']);

    if ($delete->execute()) {
        $_SESSION['status'] = "Deleted";
        $_SESSION['status_code'] = "success";
    } else {
        $_SESSION['status'] = "Delete failed";
        $_SESSION['status_code'] = "warning";
    }
}
?>

<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Content Header (Page header) -->
    <div class="content-header">
        <div class="container-fluid">
            <div class="row mb-2">
                <div class="col-sm-6">
                    <h1 class="m-0">Admin Dashboard</h1>
                </div><!-- /.col -->
                <div class="col-sm-6">
                    <ol class="breadcrumb float-sm-right">
                        <!-- Breadcrumbs can be added here if needed -->
                    </ol>
                </div><!-- /.col -->
            </div><!-- /.row -->
        </div><!-- /.container-fluid -->
    </div>
    <!-- /.content-header -->

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="card card-warning card-outline">
                <div class="card-header">
                    <h5 class="m-0">Category Form</h5>
                </div>
                <form action="" method="post">
                    <div class="card-body">
                        <div class="row">
                            <?php
                            // If editing, fetch the specific category data
                            if (isset($_POST['btnedit'])) {
                                $select = $pdo->prepare("SELECT * FROM categories WHERE category_id = :id");
                                $select->bindParam(':id', $_POST['btnedit']);
                                $select->execute();

                                if ($select) {
                                    $row = $select->fetch(PDO::FETCH_OBJ);
                                    echo '
                                    <div class="col-md-4">
                                        <div class="form-group">
                                            <label for="category">Category</label> 
                                            <input type="hidden" class="form-control" name="txtcatid" value="' . $row->category_id . '">
                                            <input type="text" class="form-control" placeholder="Enter Category" name="txtcategory" value="' . $row->category_name . '">
                                        </div>
                                        <div class="card-footer">
                                            <button type="submit" class="btn btn-info" name="btnupdate">Update</button>
                                        </div>
                                    </div>';
                                }
                            } else {
                                // Display the form for new category entry
                                echo '
                                <div class="col-md-4">
                                    <div class="form-group">
                                        <label for="category">Category</label>
                                        <input type="text" class="form-control" placeholder="Enter Category" name="txtcategory">
                                    </div>
                                    <div class="card-footer">
                                        <button type="submit" class="btn btn-warning" name="btnsave">Save</button>
                                    </div>
                                </div>';
                            }
                            ?>
                            <div class="col-md-8">
                                <table id="table_category" class="table table-striped table-hover">
                                    <thead>
                                        <tr>
                                            <th>#</th>
                                            <th>Category</th>
                                            <th>Edit</th>
                                            <th>Delete</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <?php
                                        // Fetch all categories from the new "categories" table
                                        $select = $pdo->prepare("SELECT * FROM categories ORDER BY category_id ASC");
                                        $select->execute();

                                        while ($row = $select->fetch(PDO::FETCH_OBJ)) {
                                            echo '
                                            <tr>
                                                <td>' . $row->category_id . '</td>
                                                <td>' . $row->category_name . '</td>
                                                <td>
                                                    <button type="submit" class="btn btn-primary" name="btnedit" value="' . $row->category_id . '">Edit</button>
                                                </td>
                                                <td>
                                                    <button type="submit" class="btn btn-danger" name="btndelete" value="' . $row->category_id . '">Delete</button>
                                                </td>
                                            </tr>
                                            ';
                                        }
                                        ?>
                                    </tbody>
                                    <tfoot>
                                        <tr>
                                            <th>#</th>
                                            <th>Category</th>
                                            <th>Edit</th>
                                            <th>Delete</th>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div><!-- /.row -->
                    </div><!-- /.card-body -->
                </form>
            </div><!-- /.card -->
        </div><!-- /.container-fluid -->
    </div>
    <!-- /.content -->
</div>
<!-- /.content-wrapper -->

<?php include_once "footer.php"; ?>

<?php
if (isset($_SESSION['status']) && $_SESSION['status'] != '') {
?>
    <script>
        Swal.fire({
            icon: '<?php echo $_SESSION['status_code']; ?>',
            title: '<?php echo $_SESSION['status']; ?>'
        });
    </script>
<?php
    unset($_SESSION['status']);
}
?>

<script>
    $(document).ready(function() {
        $('#table_category').DataTable();
    });
</script>
