<!-- discount.php (POS component) -->
<?php
// discount.php (POS component)
include_once 'connectdb.php'; // Connects to school_store_db
session_start();
include_once "header.php";

// Save new Discount settings
if (isset($_POST['btnsave'])) {

    // Retrieve form values
    $promotion_name = trim($_POST['promotion_name']);
    $discount_type  = trim($_POST['discount_type']);
    $discount_value = trim($_POST['discount_value']);
    $start_date     = trim($_POST['start_date']);
    $end_date       = trim($_POST['end_date']);

    // Basic validation: ensure all fields are filled
    if (empty($promotion_name) || empty($discount_type) || empty($discount_value) || empty($start_date) || empty($end_date)) {
        $_SESSION['status'] = "All fields are required";
        $_SESSION['status_code'] = "warning";
    } else {
        // Insert into promotions table
        $insert = $pdo->prepare("INSERT INTO promotions (promotion_name, discount_type, discount_value, start_date, end_date) 
                                 VALUES (:promotion_name, :discount_type, :discount_value, :start_date, :end_date)");
        $insert->bindParam(':promotion_name', $promotion_name);
        $insert->bindParam(':discount_type', $discount_type);
        $insert->bindParam(':discount_value', $discount_value);
        $insert->bindParam(':start_date', $start_date);
        $insert->bindParam(':end_date', $end_date);

        if ($insert->execute()) {
            $_SESSION['status'] = "Discount added successfully";
            $_SESSION['status_code'] = "success";
        } else {
            $_SESSION['status'] = "Discount addition failed";
            $_SESSION['status_code'] = "warning";
        }
    }
}

// Update existing Discount settings
if (isset($_POST['btnupdate'])) {

    // Retrieve form values
    $promotion_id   = trim($_POST['promotion_id']);
    $promotion_name = trim($_POST['promotion_name']);
    $discount_type  = trim($_POST['discount_type']);
    $discount_value = trim($_POST['discount_value']);
    $start_date     = trim($_POST['start_date']);
    $end_date       = trim($_POST['end_date']);

    if (empty($promotion_name) || empty($discount_type) || empty($discount_value) || empty($start_date) || empty($end_date)) {
        $_SESSION['status'] = "All fields are required";
        $_SESSION['status_code'] = "warning";
    } else {
        $update = $pdo->prepare("UPDATE promotions 
                                 SET promotion_name = :promotion_name, 
                                     discount_type = :discount_type, 
                                     discount_value = :discount_value, 
                                     start_date = :start_date, 
                                     end_date = :end_date 
                                 WHERE promotion_id = :promotion_id");
        $update->bindParam(':promotion_name', $promotion_name);
        $update->bindParam(':discount_type', $discount_type);
        $update->bindParam(':discount_value', $discount_value);
        $update->bindParam(':start_date', $start_date);
        $update->bindParam(':end_date', $end_date);
        $update->bindParam(':promotion_id', $promotion_id);

        if ($update->execute()) {
            $_SESSION['status'] = "Discount updated successfully";
            $_SESSION['status_code'] = "success";
        } else {
            $_SESSION['status'] = "Discount update failed";
            $_SESSION['status_code'] = "warning";
        }
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
                    <h1 class="m-0">Discount Management</h1>
                </div><!-- /.col -->
                <div class="col-sm-6">
                    <ol class="breadcrumb float-sm-right">
                        <!-- Breadcrumb items, if any -->
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
                    <h5 class="m-0">Discount Form</h5>
                </div>
                <form action="" method="post">
                    <div class="card-body">
                        <div class="row">
                            <?php
                            // If the "Edit" button is pressed, load existing values from promotions
                            if (isset($_POST['btnedit'])) {
                                $promotion_id = $_POST['btnedit'];
                                $select = $pdo->prepare("SELECT * FROM promotions WHERE promotion_id = :promotion_id");
                                $select->bindParam(':promotion_id', $promotion_id, PDO::PARAM_INT);
                                $select->execute();

                                if ($select) {
                                    $row = $select->fetch(PDO::FETCH_OBJ);
                                    ?>
                                    <div class="col-md-4">
                                        <!-- Hidden field to carry promotion_id -->
                                        <input type="hidden" name="promotion_id" value="<?php echo $row->promotion_id; ?>">
                                        <div class="form-group">
                                            <label for="promotion_name">Promotion Name</label>
                                            <input type="text" class="form-control" id="promotion_name" name="promotion_name" value="<?php echo $row->promotion_name; ?>" placeholder="Enter Promotion Name">
                                        </div>
                                        <div class="form-group">
                                            <label for="discount_type">Discount Type</label>
                                            <select class="form-control" id="discount_type" name="discount_type">
                                                <option value="Percentage" <?php if ($row->discount_type == 'Percentage') echo "selected"; ?>>Percentage</option>
                                                <option value="Fixed" <?php if ($row->discount_type == 'Fixed') echo "selected"; ?>>Fixed</option>
                                            </select>
                                        </div>
                                        <div class="form-group">
                                            <label for="discount_value">Discount Value</label>
                                            <input type="text" class="form-control" id="discount_value" name="discount_value" value="<?php echo $row->discount_value; ?>" placeholder="Enter Discount Value">
                                        </div>
                                        <div class="form-group">
                                            <label for="start_date">Start Date</label>
                                            <input type="date" class="form-control" id="start_date" name="start_date" value="<?php echo $row->start_date; ?>">
                                        </div>
                                        <div class="form-group">
                                            <label for="end_date">End Date</label>
                                            <input type="date" class="form-control" id="end_date" name="end_date" value="<?php echo $row->end_date; ?>">
                                        </div>
                                        <div class="card-footer">
                                            <button type="submit" class="btn btn-info" name="btnupdate">Update</button>
                                        </div>
                                    </div>
                                    <?php
                                }
                            } else {
                                // Default form for adding a new discount promotion
                                ?>
                                <div class="col-md-4">
                                    <div class="form-group">
                                        <label for="promotion_name">Promotion Name</label>
                                        <input type="text" class="form-control" id="promotion_name" name="promotion_name" placeholder="Enter Promotion Name">
                                    </div>
                                    <div class="form-group">
                                        <label for="discount_type">Discount Type</label>
                                        <select class="form-control" id="discount_type" name="discount_type">
                                            <option value="Percentage">Percentage</option>
                                            <option value="Fixed">Fixed</option>
                                        </select>
                                    </div>
                                    <div class="form-group">
                                        <label for="discount_value">Discount Value</label>
                                        <input type="text" class="form-control" id="discount_value" name="discount_value" placeholder="Enter Discount Value">
                                    </div>
                                    <div class="form-group">
                                        <label for="start_date">Start Date</label>
                                        <input type="date" class="form-control" id="start_date" name="start_date" value="<?php echo date('Y-m-d'); ?>">
                                    </div>
                                    <div class="form-group">
                                        <label for="end_date">End Date</label>
                                        <input type="date" class="form-control" id="end_date" name="end_date" value="2099-12-31">
                                    </div>
                                    <div class="card-footer">
                                        <button type="submit" class="btn btn-warning" name="btnsave">Save</button>
                                    </div>
                                </div>
                                <?php
                            }
                            ?>
                            <div class="col-md-8">
                                <table id="table_promotions" class="table table-striped table-hover">
                                    <thead>
                                        <tr>
                                            <th>#</th>
                                            <th>Promotion Name</th>
                                            <th>Type</th>
                                            <th>Value</th>
                                            <th>Start Date</th>
                                            <th>End Date</th>
                                            <th>Edit</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <?php
                                        $selectAll = $pdo->prepare("SELECT * FROM promotions ORDER BY promotion_id ASC");
                                        $selectAll->execute();
                                        while ($row = $selectAll->fetch(PDO::FETCH_OBJ)) {
                                            echo '
                                            <tr>
                                                <td>' . $row->promotion_id . '</td>
                                                <td>' . $row->promotion_name . '</td>
                                                <td>' . $row->discount_type . '</td>
                                                <td>' . $row->discount_value . '</td>
                                                <td>' . $row->start_date . '</td>
                                                <td>' . $row->end_date . '</td>
                                                <td>
                                                    <button type="submit" class="btn btn-primary" name="btnedit" value="' . $row->promotion_id . '">Edit</button>
                                                </td>
                                            </tr>
                                            ';
                                        }
                                        ?>
                                    </tbody>
                                    <tfoot>
                                        <tr>
                                            <th>#</th>
                                            <th>Promotion Name</th>
                                            <th>Type</th>
                                            <th>Value</th>
                                            <th>Start Date</th>
                                            <th>End Date</th>
                                            <th>Edit</th>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div><!-- /.row -->
                    </div><!-- /.card-body -->
                </form>
            </div><!-- /.card -->
        </div><!-- /.container-fluid -->
    </div><!-- /.content -->
</div><!-- /.content-wrapper -->

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
        $('#table_promotions').DataTable();
    });
</script>
