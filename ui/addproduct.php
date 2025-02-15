<!-- addproduct.php (POS component) -->

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

if (isset($_POST['btnsave'])) {
    // Retrieve form data
    $barcode       = trim($_POST['txtbarcode']);
    $product       = trim($_POST['txtproductname']);
    $category      = $_POST['txtselect_option']; // This now holds the category_id
    $description   = trim($_POST['txtdescription']);
    $stock         = $_POST['txtstock'];
    $purchaseprice = $_POST['txtpurchaseprice'];
    $saleprice     = $_POST['txtsaleprice'];

    // File upload processing
    $f_name       = $_FILES['myfile']['name'];
    $f_tmp        = $_FILES['myfile']['tmp_name'];
    $f_size       = $_FILES['myfile']['size'];
    $f_extension  = explode('.', $f_name);
    $f_extension  = strtolower(end($f_extension));
    $f_newfile    = uniqid() . '.' . $f_extension;
    $store        = "productimages/" . $f_newfile;

    // Allowed file extensions
    if ($f_extension == 'jpg' || $f_extension == 'jpeg' || $f_extension == 'png' || $f_extension == 'gif') {
        if ($f_size >= 1000000) {
            $_SESSION['status'] = "Max file size should be 1MB";
            $_SESSION['status_code'] = "warning";
        } else {
            if (move_uploaded_file($f_tmp, $store)) {
                $productimage = $f_newfile;

                if (empty($barcode)) {
                    // Insert without barcode first
                    $insert = $pdo->prepare("INSERT INTO products 
                        (product_name, category_id, description, stock, purchase_price, sale_price, image) 
                        VALUES (:product_name, :category_id, :description, :stock, :purchase_price, :sale_price, :image)");
                    
                    $insert->bindParam(':product_name', $product);
                    $insert->bindParam(':category_id', $category);
                    $insert->bindParam(':description', $description);
                    $insert->bindParam(':stock', $stock);
                    $insert->bindParam(':purchase_price', $purchaseprice);
                    $insert->bindParam(':sale_price', $saleprice);
                    $insert->bindParam(':image', $productimage);
                    
                    $insert->execute();

                    // Retrieve the newly inserted product ID
                    $pid = $pdo->lastInsertId();
                    date_default_timezone_set("Asia/Manila");
                    $newbarcode = $pid . date('his');

                    // Update the record with the generated barcode
                    $update = $pdo->prepare("UPDATE products SET barcode = :barcode WHERE product_id = :pid");
                    $update->bindParam(':barcode', $newbarcode);
                    $update->bindParam(':pid', $pid);
                    
                    if ($update->execute()) {
                        $_SESSION['status'] = "Product Inserted Successfully";
                        $_SESSION['status_code'] = "success";
                    } else {
                        $_SESSION['status'] = "Product Insertion Failed";
                        $_SESSION['status_code'] = "error";
                    }
                } else {
                    // Insert with the provided barcode
                    $insert = $pdo->prepare("INSERT INTO products 
                        (barcode, product_name, category_id, description, stock, purchase_price, sale_price, image) 
                        VALUES (:barcode, :product_name, :category_id, :description, :stock, :purchase_price, :sale_price, :image)");
                    
                    $insert->bindParam(':barcode', $barcode);
                    $insert->bindParam(':product_name', $product);
                    $insert->bindParam(':category_id', $category);
                    $insert->bindParam(':description', $description);
                    $insert->bindParam(':stock', $stock);
                    $insert->bindParam(':purchase_price', $purchaseprice);
                    $insert->bindParam(':sale_price', $saleprice);
                    $insert->bindParam(':image', $productimage);
                    
                    if ($insert->execute()) {
                        $_SESSION['status'] = "Product Inserted";
                        $_SESSION['status_code'] = "success";
                    } else {
                        $_SESSION['status'] = "Product Insertion Failed";
                        $_SESSION['status_code'] = "error";
                    }
                }
            }
        }
    } else {
        $_SESSION['status'] = "Only jpg, jpeg, png, and gif files can be uploaded";
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
                    <h1 class="m-0">Add Product</h1>
                </div><!-- /.col -->
                <div class="col-sm-6">
                    <ol class="breadcrumb float-sm-right">
                        <!-- You can add breadcrumbs here if needed -->
                    </ol>
                </div><!-- /.col -->
            </div><!-- /.row -->
        </div><!-- /.container-fluid -->
    </div>
    <!-- /.content-header -->

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="row">
                <div class="col-lg-12">
                    <div class="card card-primary card-outline">
                        <div class="card-header">
                            <h5 class="m-0">Product</h5>
                        </div>
                        <form action="" method="post" enctype="multipart/form-data">
                            <div class="card-body">
                                <div class="row">
                                    <!-- Left Column -->
                                    <div class="col-md-6">
                                        <div class="form-group">
                                            <label>Barcode</label>
                                            <input type="text" class="form-control" placeholder="Enter Barcode" name="txtbarcode">
                                        </div>
                                        <div class="form-group">
                                            <label>Product Name</label>
                                            <input type="text" class="form-control" placeholder="Enter Name" name="txtproductname" required>
                                        </div>
                                        <div class="form-group">
                                            <label>Category</label>
                                            <select class="form-control" name="txtselect_option" required>
                                                <option value="" selected disabled>Select Category</option>
                                                <?php
                                                // Fetch categories from the new "categories" table
                                                $select = $pdo->prepare("SELECT * FROM categories ORDER BY category_name ASC");
                                                $select->execute();
                                                while ($row = $select->fetch(PDO::FETCH_ASSOC)) {
                                                    // Use category_id as the option value
                                                    echo '<option value="' . $row['category_id'] . '">' . $row['category_name'] . '</option>';
                                                }
                                                ?>
                                            </select>
                                        </div>
                                        <div class="form-group">
                                            <label>Description</label>
                                            <textarea class="form-control" placeholder="Enter Description" name="txtdescription" rows="4" required></textarea>
                                        </div>
                                    </div>
                                    <!-- Right Column -->
                                    <div class="col-md-6">
                                        <div class="form-group">
                                            <label>Stock Quantity</label>
                                            <input type="number" min="1" class="form-control" placeholder="Enter Stock" name="txtstock" required>
                                        </div>
                                        <div class="form-group">
                                            <label>Purchase Price</label>
                                            <input type="number" min="0" step="0.01" class="form-control" placeholder="Enter Purchase Price" name="txtpurchaseprice" required>
                                        </div>
                                        <div class="form-group">
                                            <label>Sale Price</label>
                                            <input type="number" min="0" step="0.01" class="form-control" placeholder="Enter Sale Price" name="txtsaleprice" required>
                                        </div>
                                        <div class="form-group">
                                            <label>Product Image</label>
                                            <input type="file" class="input-group" name="myfile" required>
                                            <p>Upload Image</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <!-- Save Button -->
                            <div class="card-footer">
                                <div class="text-center">
                                    <button type="submit" class="btn btn-primary" name="btnsave">Save Product</button>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>
                <!-- /.col-lg-12 -->
            </div>
            <!-- /.row -->
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
